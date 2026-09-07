from flask import Flask, request, jsonify, g
from flask_cors import CORS
import uuid
from datetime import datetime
from sqlalchemy import create_engine, text
from contextlib import contextmanager
import os
import json
from kafka import KafkaProducer
import redis
from metrics_middleware import setup_metrics
from auth_middleware import require_auth
from permissions import require_role, is_admin, can_modify

app = Flask(__name__)
CORS(app)

# 🎯 הפעלת Monitoring
setup_metrics(app)

# 🔧 Configuration מ-Environment Variables
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:example@localhost:5432/mydatabase')
KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')
REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
SERVICE_PORT = int(os.environ.get('SERVICE_PORT', 5003))

# Kafka Producer
kafka_producer = KafkaProducer(
    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

# Redis Client
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# Database setup
engine = create_engine(DATABASE_URL)

# סף אישור - העברות מעל $200 דורשות אישור ידני
APPROVAL_THRESHOLD = 20000  # 20000 cents = $200


def publish_transaction_event(transaction_id, initiator_id, amount, txn_type,
                              from_account_id=None, to_account_id=None):
    """Publish one event per row written to the transactions table.

    Consumed by fraud-detection-service. Deliberately best-effort: this is called
    after the DB commit and swallows its own errors, because a Kafka outage must
    never fail a banking operation that already succeeded. This differs from the
    transfer() producer, where the event drives the workflow and failing loud is
    correct.
    """
    try:
        kafka_producer.send('transactions', value={
            'transaction_id': transaction_id,
            'initiator_id': initiator_id,
            'from_account_id': from_account_id,
            'to_account_id': to_account_id,
            'amount': amount,
            'type': txn_type,
            'timestamp': datetime.now().isoformat()
        })
        kafka_producer.flush()
    except Exception as e:
        app.logger.error(f"Failed to publish transaction event {transaction_id}: {e}")

@contextmanager
def get_db_connection():
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
        transaction.commit()
    except Exception as e:
        transaction.rollback()
        raise
    finally:
        connection.close()

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "transaction-service"}), 200

@app.route('/transactions/<account_id>/deposit', methods=['POST'])
@require_auth
@require_role('admin', 'user')
def deposit(account_id):
    """Deposit money to account - Only admin and user"""
    user_id = g.user_id
    
    data = request.get_json()
    amount = data.get('amount')
    
    if not amount or amount <= 0:
        return jsonify({"error": "Invalid amount"}), 400
    
    try:
        with get_db_connection() as connection:
            # Admin can deposit to any account
            if is_admin():
                account = connection.execute(
                    text('SELECT * FROM accounts WHERE id = :account_id'),
                    {'account_id': account_id}
                ).fetchone()
            else:
                # Regular users can only deposit to their own accounts
                account = connection.execute(
                    text('SELECT * FROM accounts WHERE id = :account_id AND owner_id = :user_id'),
                    {'account_id': account_id, 'user_id': user_id}
                ).fetchone()
            
            if not account:
                return jsonify({"error": "Account not found or unauthorized"}), 403
            
            connection.execute(
                text('UPDATE accounts SET balance_cents = balance_cents + :amount, updated_at = :updated_at WHERE id = :account_id'),
                {'amount': amount, 'account_id': account_id, 'updated_at': datetime.now()}
            )
            
            transaction_id = str(uuid.uuid4())
            connection.execute(
                text("""
                    INSERT INTO transactions 
                    (id, initiator_id, to_bank_account_id, amount, created_at, updated_at)
                    VALUES (:id, :initiator_id, :to_bank_account_id, :amount, :created_at, :updated_at)
                """),
                {
                    'id': transaction_id,
                    'initiator_id': user_id,
                    'to_bank_account_id': account_id,
                    'amount': amount,
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                }
            )
        
        publish_transaction_event(
            transaction_id, user_id, amount, 'deposit',
            to_account_id=account_id
        )

        return jsonify({"message": "Deposit successful", "transaction_id": transaction_id}), 200
    
    except Exception as e:
        app.logger.error(f"Deposit failed: {str(e)}")
        return jsonify({"error": "Internal server error", "message": "Failed to process deposit"}), 500

@app.route('/transactions/<account_id>/withdraw', methods=['POST'])
@require_auth
@require_role('admin', 'user')
def withdraw(account_id):
    """Withdraw money from account - Only admin and user"""
    user_id = g.user_id
    
    data = request.get_json()
    amount = data.get('amount')
    
    if not amount or amount <= 0:
        return jsonify({"error": "Invalid amount"}), 400
    
    try:
        with get_db_connection() as connection:
            # Admin can withdraw from any account
            if is_admin():
                account = connection.execute(
                    text('SELECT * FROM accounts WHERE id = :account_id'),
                    {'account_id': account_id}
                ).fetchone()
            else:
                # Regular users can only withdraw from their own accounts
                account = connection.execute(
                    text('SELECT * FROM accounts WHERE id = :account_id AND owner_id = :user_id'),
                    {'account_id': account_id, 'user_id': user_id}
                ).fetchone()
            
            if not account:
                return jsonify({"error": "Account not found or unauthorized"}), 403
            
            if account.balance_cents < amount:
                return jsonify({
                    "error": "Insufficient funds", 
                    "current_balance": account.balance_cents
                }), 400
            
            connection.execute(
                text('UPDATE accounts SET balance_cents = balance_cents - :amount, updated_at = :updated_at WHERE id = :account_id'),
                {'amount': amount, 'account_id': account_id, 'updated_at': datetime.now()}
            )
            
            transaction_id = str(uuid.uuid4())
            connection.execute(
                text("""
                    INSERT INTO transactions 
                    (id, initiator_id, from_bank_account_id, amount, created_at, updated_at)
                    VALUES (:id, :initiator_id, :from_bank_account_id, :amount, :created_at, :updated_at)
                """),
                {
                    'id': transaction_id,
                    'initiator_id': user_id,
                    'from_bank_account_id': account_id,
                    'amount': amount,
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                }
            )
        
        publish_transaction_event(
            transaction_id, user_id, amount, 'withdrawal',
            from_account_id=account_id
        )

        return jsonify({"message": "Withdrawal successful", "transaction_id": transaction_id}), 200
    
    except ValueError as e:
        return jsonify({"error": "Invalid input", "details": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Withdrawal failed: {str(e)}")
        return jsonify({"error": "Internal server error", "message": "Failed to process withdrawal"}), 500

@app.route('/transactions/<from_account_id>/transfer', methods=['POST'])
@require_auth
@require_role('admin', 'user')
def transfer(from_account_id):
    """Create a transfer request - Only admin and user"""
    user_id = g.user_id
    
    data = request.get_json()
    amount = data.get('amount')
    to_account_id = data.get('to_account_id')
    
    if not amount or amount <= 0:
        return jsonify({"error": "Invalid amount"}), 400
    
    if not to_account_id:
        return jsonify({"error": "Destination account required"}), 400
    
    try:
        with get_db_connection() as connection:
            # Admin can transfer from any account
            if is_admin():
                from_account = connection.execute(
                    text('SELECT * FROM accounts WHERE id = :from_account_id'),
                    {'from_account_id': from_account_id}
                ).fetchone()
            else:
                # Regular users can only transfer from their own accounts
                from_account = connection.execute(
                    text('SELECT * FROM accounts WHERE id = :from_account_id AND owner_id = :user_id'),
                    {'from_account_id': from_account_id, 'user_id': user_id}
                ).fetchone()
            
            if not from_account:
                return jsonify({"error": "Source account not found or unauthorized"}), 403
            
            if from_account.balance_cents < amount:
                return jsonify({
                    "error": "Insufficient funds",
                    "current_balance": from_account.balance_cents,
                    "requested_amount": amount
                }), 400
            
            to_account = connection.execute(
                text('SELECT id FROM accounts WHERE id = :to_account_id'),
                {'to_account_id': to_account_id}
            ).fetchone()
            
            if not to_account:
                return jsonify({"error": "Destination account not found"}), 404
            
            requires_approval = amount > APPROVAL_THRESHOLD
            initial_state = "pending" if requires_approval else "approved"
            
            transfer_request_id = str(uuid.uuid4())
            connection.execute(
                text("""
                    INSERT INTO transfer_requests 
                    (id, initiator_id, from_account_id, to_account_id, amount, state, requires_approval, created_at, updated_at)
                    VALUES (:id, :initiator_id, :from_account_id, :to_account_id, :amount, :state, :requires_approval, :created_at, :updated_at)
                """),
                {
                    'id': transfer_request_id,
                    'initiator_id': user_id,
                    'from_account_id': from_account_id,
                    'to_account_id': to_account_id,
                    'amount': amount,
                    'state': initial_state,
                    'requires_approval': requires_approval,
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                }
            )
            
            redis_client.hset(
                f"transfer:{transfer_request_id}",
                mapping={
                    'state': initial_state,
                    'amount': amount,
                    # Cached so get_transfer_status() can authorize a cache hit without
                    # touching the DB. Safe to cache only because initiator_id is written
                    # once here and never updated afterwards - if it ever becomes mutable,
                    # the status endpoint must authorize against the DB instead.
                    'initiator_id': user_id,
                    'from_account_id': from_account_id,
                    'to_account_id': to_account_id,
                    'requires_approval': str(requires_approval)
                }
            )
            redis_client.expire(f"transfer:{transfer_request_id}", 86400)
            
            kafka_message = {
                'transfer_request_id': transfer_request_id,
                'initiator_id': user_id,
                'from_account_id': from_account_id,
                'to_account_id': to_account_id,
                'amount': amount,
                'state': initial_state,
                'requires_approval': requires_approval,
                'timestamp': datetime.now().isoformat()
            }
            
            kafka_producer.send('transfer-requests', value=kafka_message)
            kafka_producer.flush()
        
        return jsonify({
            "message": "Transfer request created",
            "transfer_request_id": transfer_request_id,
            "state": initial_state,
            "requires_approval": requires_approval
        }), 202
    
    except ValueError as e:
        return jsonify({"error": "Invalid input", "details": str(e)}), 400
    except KeyError as e:
        return jsonify({"error": "Missing required field", "field": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Transfer creation failed: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({
            "error": "Internal server error",
            "message": "Failed to create transfer request"
        }), 500

@app.route('/transfers/<transfer_request_id>/status', methods=['GET'])
@require_auth
def get_transfer_status(transfer_request_id):
    """Get transfer request status - All roles can view"""
    user_id = g.user_id
    
    try:
        redis_data = redis_client.hgetall(f"transfer:{transfer_request_id}")

        # The cache may only answer if it can prove ownership. Entries written before
        # initiator_id was added to the hash - and keys resurrected by a writer after
        # the TTL expired - carry no initiator_id, so they fall through to the database
        # path below, which re-checks ownership against transfer_requests.
        cached_initiator_id = redis_data.get('initiator_id') if redis_data else None

        if cached_initiator_id:
            # Admins bypass the ownership check, matching the database path.
            # Non-owners get the same 404 the database path returns, so the response
            # cannot be used to distinguish an existing transfer from a missing one.
            if not is_admin() and cached_initiator_id != str(user_id):
                return jsonify({"error": "Transfer request not found"}), 404

            return jsonify({
                "transfer_request_id": transfer_request_id,
                "state": redis_data.get('state'),
                "amount": int(redis_data.get('amount', 0)),
                "requires_approval": redis_data.get('requires_approval') == 'True',
                "source": "redis"
            }), 200

        with get_db_connection() as connection:
            # Admin can see any transfer
            if is_admin():
                transfer = connection.execute(
                    text('SELECT * FROM transfer_requests WHERE id = :id'),
                    {'id': transfer_request_id}
                ).fetchone()
            else:
                # Regular users can only see their own transfers
                transfer = connection.execute(
                    text('SELECT * FROM transfer_requests WHERE id = :id AND initiator_id = :initiator_id'),
                    {'id': transfer_request_id, 'initiator_id': user_id}
                ).fetchone()
            
            if not transfer:
                return jsonify({"error": "Transfer request not found"}), 404
            
            return jsonify({
                "transfer_request_id": str(transfer.id),
                "state": transfer.state,
                "amount": transfer.amount,
                "requires_approval": transfer.requires_approval,
                "transaction_id": str(transfer.transaction_id) if transfer.transaction_id else None,
                "created_at": transfer.created_at.isoformat(),
                "updated_at": transfer.updated_at.isoformat(),
                "source": "database"
            }), 200
    
    except Exception as e:
        app.logger.error(f"Failed to get transfer status: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/transfers/<transfer_request_id>/approve', methods=['POST'])
@require_auth
@require_role('admin')
def approve_transfer(transfer_request_id):
    """Approve a pending transfer - Only admin"""
    user_id = g.user_id
    
    try:
        with get_db_connection() as connection:
            transfer = connection.execute(
                text('SELECT * FROM transfer_requests WHERE id = :id'),
                {'id': transfer_request_id}
            ).fetchone()
            
            if not transfer:
                return jsonify({"error": "Transfer request not found"}), 404
            
            if transfer.state != 'pending':
                return jsonify({"error": f"Transfer is in '{transfer.state}' state, cannot approve"}), 400
            
            connection.execute(
                text("""
                    UPDATE transfer_requests 
                    SET state = 'approved', approved_by = :approved_by, updated_at = :updated_at 
                    WHERE id = :id
                """),
                {
                    'id': transfer_request_id,
                    'approved_by': user_id,
                    'updated_at': datetime.now()
                }
            )
            
            redis_client.hset(f"transfer:{transfer_request_id}", 'state', 'approved')
            
            kafka_message = {
                'transfer_request_id': transfer_request_id,
                'state': 'approved',
                'approved_by': user_id,
                'timestamp': datetime.now().isoformat()
            }
            
            kafka_producer.send('transfer-approvals', value=kafka_message)
            kafka_producer.flush()
        
        return jsonify({
            "message": "Transfer approved",
            "transfer_request_id": transfer_request_id,
            "state": "approved"
        }), 200
    
    except Exception as e:
        app.logger.error(f"Failed to approve transfer: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/transfers/<transfer_request_id>/decline', methods=['POST'])
@require_auth
@require_role('admin')
def decline_transfer(transfer_request_id):
    """Decline a pending transfer - Only admin"""
    user_id = g.user_id
    
    data = request.get_json()
    decline_reason = data.get('reason', 'Declined by administrator')
    
    try:
        with get_db_connection() as connection:
            transfer = connection.execute(
                text('SELECT * FROM transfer_requests WHERE id = :id'),
                {'id': transfer_request_id}
            ).fetchone()
            
            if not transfer:
                return jsonify({"error": "Transfer request not found"}), 404
            
            if transfer.state != 'pending':
                return jsonify({"error": f"Transfer is in '{transfer.state}' state, cannot decline"}), 400
            
            connection.execute(
                text("""
                    UPDATE transfer_requests 
                    SET state = 'declined', decline_reason = :reason, updated_at = :updated_at 
                    WHERE id = :id
                """),
                {
                    'id': transfer_request_id,
                    'reason': decline_reason,
                    'updated_at': datetime.now()
                }
            )
            
            redis_client.hset(f"transfer:{transfer_request_id}", 'state', 'declined')
            
            kafka_message = {
                'transfer_request_id': transfer_request_id,
                'state': 'declined',
                'decline_reason': decline_reason,
                'timestamp': datetime.now().isoformat()
            }
            
            kafka_producer.send('transfer-declines', value=kafka_message)
            kafka_producer.flush()
        
        return jsonify({
            "message": "Transfer declined",
            "transfer_request_id": transfer_request_id,
            "state": "declined",
            "reason": decline_reason
        }), 200
    
    except Exception as e:
        app.logger.error(f"Failed to decline transfer: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/transactions/<account_id>/history', methods=['GET'])
@require_auth
def get_transaction_history(account_id):
    """Get transaction history for account - All roles can view"""
    user_id = g.user_id
    
    try:
        with get_db_connection() as connection:
            # Admin can see any account's history
            if is_admin():
                account = connection.execute(
                    text('SELECT * FROM accounts WHERE id = :account_id'),
                    {'account_id': account_id}
                ).fetchone()
            else:
                # Regular users can only see their own account's history
                account = connection.execute(
                    text('SELECT * FROM accounts WHERE id = :account_id AND owner_id = :user_id'),
                    {'account_id': account_id, 'user_id': user_id}
                ).fetchone()
            
            if not account:
                return jsonify({"error": "Account not found or unauthorized"}), 403
            
            transactions = connection.execute(
                text("""
                    SELECT * FROM transactions 
                    WHERE from_bank_account_id = :account_id 
                    OR to_bank_account_id = :account_id 
                    ORDER BY created_at DESC
                """),
                {'account_id': account_id}
            ).fetchall()
            
            transaction_list = [
                {
                    'id': str(t.id),
                    'type': 'withdrawal' if str(t.from_bank_account_id) == account_id else 'deposit',
                    'amount': t.amount,
                    'from_account': str(t.from_bank_account_id) if t.from_bank_account_id else None,
                    'to_account': str(t.to_bank_account_id) if t.to_bank_account_id else None,
                    'created_at': t.created_at.isoformat()
                }
                for t in transactions
            ]
        
        return jsonify({"transactions": transaction_list}), 200
    
    except Exception as e:
        app.logger.error(f"Failed to get transaction history: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=SERVICE_PORT)