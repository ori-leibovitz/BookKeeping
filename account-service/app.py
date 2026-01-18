from flask import Flask, request, jsonify, g
from flask_cors import CORS
import uuid
from datetime import datetime
from sqlalchemy import create_engine, text
from contextlib import contextmanager
import os
from metrics_middleware import setup_metrics
from auth_middleware import require_auth
from permissions import require_role, is_admin, can_modify

app = Flask(__name__)
CORS(app)

# 🎯 הפעלת Monitoring
setup_metrics(app)

# 🔧 Configuration מ-Environment Variables
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:example@localhost:5432/mydatabase')
SERVICE_PORT = int(os.environ.get('SERVICE_PORT', 5002))

# Database setup
engine = create_engine(DATABASE_URL)

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
    return jsonify({"status": "ok", "service": "account-service"}), 200

@app.route('/accounts', methods=['POST'])
@require_auth
@require_role('admin', 'user')
def create_account():
    """Create a new bank account - Only admin and user"""
    user_id = g.user_id
    
    data = request.get_json()
    
    # Validation
    balance_cents = data.get('balance_cents', 0)
    if balance_cents < 0:
        return jsonify({"error": "Initial balance cannot be negative"}), 400
    
    account_id = str(uuid.uuid4())
    account_number = str(uuid.uuid4())
    
    try:
        with get_db_connection() as connection:
            connection.execute(
                text(
                    "INSERT INTO accounts (id, owner_id, account_number, type, balance_cents, created_at, updated_at) "
                    "VALUES (:account_id, :owner_id, :account_number, :type, :balance_cents, :created_at, :updated_at)"
                ),
                {
                    'account_id': account_id,
                    'owner_id': user_id,
                    'account_number': account_number,
                    'type': data.get('type', 'checking'),
                    'balance_cents': balance_cents,
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                }
            )
        
        return jsonify({"id": account_id, "account_number": account_number}), 201
    
    except Exception as e:
        app.logger.error(f"Failed to create account: {str(e)}")
        return jsonify({"error": "Internal server error", "message": "Failed to create account"}), 500

@app.route('/accounts', methods=['GET'])
@require_auth
@require_role('admin', 'user', 'viewer')  # כולם יכולים לראות
def list_accounts():
    """List accounts - Admin sees all, others see only their own"""
    user_id = g.user_id
    
    # Admin can see all accounts
    if is_admin():
        try:
            with get_db_connection() as connection:
                accounts = connection.execute(
                    text("SELECT * FROM accounts ORDER BY created_at DESC")
                ).fetchall()
                
                account_list = [
                    {
                        'id': str(acc.id),
                        'owner_id': str(acc.owner_id),
                        'account_number': acc.account_number,
                        'type': acc.type,
                        'balance_cents': acc.balance_cents,
                        'created_at': acc.created_at.isoformat()
                    }
                    for acc in accounts
                ]
            
            return jsonify({"accounts": account_list, "view": "admin", "total": len(account_list)}), 200
        
        except Exception as e:
            app.logger.error(f"Failed to list accounts: {str(e)}")
            return jsonify({"error": "Internal server error"}), 500
    
    # Regular users see only their own accounts
    try:
        with get_db_connection() as connection:
            accounts = connection.execute(
                text("SELECT * FROM accounts WHERE owner_id = :owner_id ORDER BY created_at DESC"),
                {'owner_id': user_id}
            ).fetchall()
            
            account_list = [
                {
                    'id': str(acc.id),
                    'account_number': acc.account_number,
                    'type': acc.type,
                    'balance_cents': acc.balance_cents,
                    'created_at': acc.created_at.isoformat()
                }
                for acc in accounts
            ]
        
        return jsonify({"accounts": account_list}), 200
    
    except Exception as e:
        app.logger.error(f"Failed to list accounts: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/accounts/<account_id>', methods=['GET'])
@require_auth
def get_account(account_id):
    """Get specific account details - Admin can see any, others only their own"""
    user_id = g.user_id
    
    try:
        with get_db_connection() as connection:
            # Admin can see any account
            if is_admin():
                account = connection.execute(
                    text("SELECT * FROM accounts WHERE id = :account_id"),
                    {'account_id': account_id}
                ).fetchone()
            else:
                # Regular users can only see their own accounts
                account = connection.execute(
                    text("SELECT * FROM accounts WHERE id = :account_id AND owner_id = :owner_id"),
                    {'account_id': account_id, 'owner_id': user_id}
                ).fetchone()
            
            if not account:
                return jsonify({"error": "Account not found"}), 404
            
            return jsonify({
                'id': str(account.id),
                'account_number': account.account_number,
                'type': account.type,
                'balance_cents': account.balance_cents,
                'created_at': account.created_at.isoformat()
            }), 200
    
    except Exception as e:
        app.logger.error(f"Failed to get account: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=SERVICE_PORT)