"""Fraud detection consumer.

Reads the `transactions` stream, scores every transaction with a trained
Isolation Forest, persists the score to Postgres, and publishes only the flagged
ones to `fraud-alerts`.

Scoring is post-hoc: the money has already moved by the time an event arrives.
This service observes and alerts, it never blocks a transaction.
"""

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime

from kafka import KafkaConsumer, KafkaProducer
from sqlalchemy import create_engine, text

from fraud_metrics import (
    fraud_model_info,
    fraud_score_distribution,
    fraud_scoring_duration_seconds,
    fraud_scoring_errors_total,
    fraud_transactions_scored_total,
    setup_metrics,
)
from scorer import FraudScorer, ModelArtifactError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:example@localhost:5432/mydatabase')
KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
MODEL_PATH = os.environ.get('MODEL_PATH', '/app/models/isolation_forest.joblib')
METRICS_PORT = int(os.environ.get('METRICS_PORT', 5005))

# Optional: overrides the threshold baked into model_meta.json at training time.
_threshold_env = os.environ.get('FRAUD_THRESHOLD', '').strip()
FRAUD_THRESHOLD = float(_threshold_env) if _threshold_env else None

SOURCE_TOPIC = 'transactions'
ALERT_TOPIC = 'fraud-alerts'
CONSUMER_GROUP = 'fraud-detection-group'

engine = create_engine(DATABASE_URL)

kafka_producer = KafkaProducer(
    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)


@contextmanager
def get_db_connection():
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
        transaction.commit()
    except Exception:
        transaction.rollback()
        raise
    finally:
        connection.close()


def persist_score(transaction_id, score, is_flagged, features, model_version):
    """Write the verdict to fraud_scores. Returns True if a row was inserted.

    ON CONFLICT makes this idempotent: Kafka is at-least-once, so the same event
    can legitimately arrive twice after a rebalance or restart. The return value
    is what makes alerting idempotent too -- the database is the single arbiter
    of whether this transaction has already been judged, so a replay re-scores
    (cheap, deterministic) but does not re-alert.
    """
    with get_db_connection() as connection:
        result = connection.execute(
            text("""
                INSERT INTO fraud_scores
                (id, transaction_id, score, is_flagged, model_version, features, scored_at)
                VALUES (:id, :transaction_id, :score, :is_flagged, :model_version,
                        CAST(:features AS JSONB), :scored_at)
                ON CONFLICT ON CONSTRAINT fraud_scores_txn_model_unique DO NOTHING
            """),
            {
                'id': str(uuid.uuid4()),
                'transaction_id': transaction_id,
                'score': round(score, 5),
                'is_flagged': is_flagged,
                'model_version': model_version,
                'features': json.dumps(features),
                'scored_at': datetime.now(),
            }
        )
        return result.rowcount > 0


def publish_alert(txn, score, threshold, model_version):
    """Publish a flagged transaction. Carries enough context that a consumer
    does not need to query the database to act on it."""
    kafka_producer.send(ALERT_TOPIC, value={
        'transaction_id': txn.get('transaction_id'),
        'initiator_id': txn.get('initiator_id'),
        'from_account_id': txn.get('from_account_id'),
        'to_account_id': txn.get('to_account_id'),
        'amount': txn.get('amount'),
        'type': txn.get('type'),
        'transaction_timestamp': txn.get('timestamp'),
        'score': round(score, 5),
        'threshold': threshold,
        'model_version': model_version,
        'flagged_at': datetime.now().isoformat(),
    })
    kafka_producer.flush()


def process_transaction(scorer, txn):
    """Score one transaction event and record the outcome."""
    transaction_id = txn.get('transaction_id')
    if not transaction_id:
        fraud_scoring_errors_total.labels(error_type='malformed_event').inc()
        logger.error(f"Event has no transaction_id, skipping: {txn}")
        return

    try:
        with fraud_scoring_duration_seconds.time():
            score, is_flagged, features = scorer.score(txn)
    except ValueError as e:
        fraud_scoring_errors_total.labels(error_type='malformed_event').inc()
        logger.error(f"Malformed event {transaction_id}: {e}")
        return
    except Exception as e:
        fraud_scoring_errors_total.labels(error_type='scoring_failed').inc()
        logger.error(f"Scoring failed for {transaction_id}: {e}")
        return

    fraud_score_distribution.observe(score)
    fraud_transactions_scored_total.labels(
        result='flagged' if is_flagged else 'clean'
    ).inc()

    if is_flagged:
        logger.warning(
            f"🚨 FLAGGED {transaction_id}: score={score:.4f} "
            f"(threshold {scorer.threshold:.2f}) "
            f"type={txn.get('type')} amount=${txn.get('amount', 0) / 100:.2f}"
        )
    else:
        logger.info(f"✅ Clean {transaction_id}: score={score:.4f}")

    try:
        is_new = persist_score(transaction_id, score, is_flagged, features, scorer.model_version)
    except Exception as e:
        fraud_scoring_errors_total.labels(error_type='db_write_failed').inc()
        logger.error(f"Failed to persist score for {transaction_id}: {e}")
        # Without a confirmed write we cannot tell a replay from a first sight,
        # so alert rather than risk swallowing a genuine one.
        is_new = True

    if is_flagged and not is_new:
        logger.info(f"Replay of already-judged {transaction_id}, not re-alerting")

    if is_flagged and is_new:
        try:
            publish_alert(txn, score, scorer.threshold, scorer.model_version)
        except Exception as e:
            fraud_scoring_errors_total.labels(error_type='alert_publish_failed').inc()
            logger.error(f"Failed to publish alert for {transaction_id}: {e}")


def wait_for_kafka(max_retries=30):
    """Same startup handshake the transfer processor uses."""
    for attempt in range(1, max_retries + 1):
        try:
            probe = KafkaConsumer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                consumer_timeout_ms=1000
            )
            probe.close()
            logger.info("✅ Successfully connected to Kafka")
            return True
        except Exception:
            logger.warning(f"⏳ Waiting for Kafka... (attempt {attempt}/{max_retries})")
            time.sleep(2)
    return False


def main():
    logger.info("🚀 Starting Fraud Detection Service...")

    # Load the model before anything else: a bad artifact should stop the
    # service at boot, not surface as wrong scores under load.
    try:
        scorer = FraudScorer(MODEL_PATH, threshold_override=FRAUD_THRESHOLD)
    except ModelArtifactError as e:
        logger.error(f"❌ Cannot load model: {e}")
        raise SystemExit(1)

    logger.info(
        f"🧠 Model v{scorer.model_version} loaded (trained {scorer.trained_at}), "
        f"threshold={scorer.threshold:.2f}"
    )

    setup_metrics(METRICS_PORT, scorer.model_version, scorer.threshold)
    logger.info(f"📊 Metrics exposed on :{METRICS_PORT}/metrics")

    if not wait_for_kafka():
        logger.error("❌ Failed to connect to Kafka after maximum retries")
        return

    consumer = KafkaConsumer(
        SOURCE_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_deserializer=lambda m: json.loads(m.decode('utf-8')),
        group_id=CONSUMER_GROUP,
        auto_offset_reset='earliest',
        enable_auto_commit=True,
        max_poll_interval_ms=300000
    )

    logger.info(f"👂 Listening on '{SOURCE_TOPIC}', alerting on '{ALERT_TOPIC}'...")

    try:
        while True:
            messages = consumer.poll(timeout_ms=1000, max_records=100)

            for topic_partition, records in messages.items():
                for message in records:
                    try:
                        process_transaction(scorer, message.value)
                    except Exception as e:
                        fraud_scoring_errors_total.labels(error_type='scoring_failed').inc()
                        logger.error(f"Error processing message: {e}")
                        import traceback
                        traceback.print_exc()

            time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("🛑 Shutting down Fraud Detection Service...")
    finally:
        consumer.close()


if __name__ == '__main__':
    main()
