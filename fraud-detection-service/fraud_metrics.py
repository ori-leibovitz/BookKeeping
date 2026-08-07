"""Prometheus metrics for the fraud detection consumer.

This service is a Kafka worker with no Flask app, so it cannot reuse the
metrics_middleware.py that the REST services share. Instead it runs
prometheus_client's own WSGI server on a daemon thread.

Note there is deliberately no fraud_flagged_ratio gauge. The flagged rate is a
ratio of two counters and belongs in PromQL, where it stays correct across
restarts:

    rate(fraud_transactions_scored_total{result="flagged"}[5m])
      / rate(fraud_transactions_scored_total[5m])
"""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# result = flagged | clean
fraud_transactions_scored_total = Counter(
    'fraud_transactions_scored_total',
    'Transactions scored by the fraud model',
    ['result'],
)

# Buckets span the full 0..1 score range at the same 0.05 resolution used by the
# threshold sweep in train_model.py, so Grafana and the calibration report line up.
fraud_score_distribution = Histogram(
    'fraud_score_distribution',
    'Distribution of fraud scores (0 = normal, 1 = most suspicious)',
    buckets=(0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50,
             0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.0),
)

fraud_scoring_duration_seconds = Histogram(
    'fraud_scoring_duration_seconds',
    'Time to extract features and score one transaction',
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
)

# error_type = malformed_event | scoring_failed | db_write_failed | alert_publish_failed
fraud_scoring_errors_total = Counter(
    'fraud_scoring_errors_total',
    'Errors encountered while processing transaction events',
    ['error_type'],
)

fraud_model_info = Gauge(
    'fraud_model_info',
    'Always 1; the labels carry the loaded model version and threshold',
    ['version', 'threshold'],
)


def setup_metrics(port, model_version, threshold):
    """Start the metrics endpoint and publish which model is live."""
    start_http_server(port)
    fraud_model_info.labels(version=model_version, threshold=f"{threshold:.2f}").set(1)
