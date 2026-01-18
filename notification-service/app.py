from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from datetime import datetime
import logging
from metrics_middleware import setup_metrics

app = Flask(__name__)
CORS(app)

# 🎯 הפעלת Monitoring
setup_metrics(app)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔧 Configuration מ-Environment Variables
EMAIL_ENABLED = os.environ.get('EMAIL_ENABLED', 'false').lower() == 'true'
SMS_ENABLED = os.environ.get('SMS_ENABLED', 'false').lower() == 'true'
SERVICE_PORT = int(os.environ.get('SERVICE_PORT', 5004))  # 👈 Port מ-ENV!

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "notification-service"}), 200

@app.route('/notifications/email', methods=['POST'])
def send_email():
    """Send email notification"""
    try:
        data = request.get_json()
        
        to_email = data.get('to')
        subject = data.get('subject')
        body = data.get('body')
        
        if not all([to_email, subject, body]):
            return jsonify({"error": "Missing required fields"}), 400
        
        # Log the email
        logger.info(f"""
        ===== EMAIL NOTIFICATION =====
        To: {to_email}
        Subject: {subject}
        Body: {body}
        Timestamp: {datetime.now().isoformat()}
        ==============================
        """)
        
        if EMAIL_ENABLED:
            # TODO: Integrate with actual email service (SendGrid, SES, etc.)
            pass
        
        return jsonify({
            "message": "Email notification sent (logged)",
            "to": to_email,
            "subject": subject
        }), 200
    
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/notifications/sms', methods=['POST'])
def send_sms():
    """Send SMS notification"""
    try:
        data = request.get_json()
        
        to_phone = data.get('to')
        message = data.get('message')
        
        if not all([to_phone, message]):
            return jsonify({"error": "Missing required fields"}), 400
        
        # Log the SMS
        logger.info(f"""
        ===== SMS NOTIFICATION =====
        To: {to_phone}
        Message: {message}
        Timestamp: {datetime.now().isoformat()}
        ============================
        """)
        
        if SMS_ENABLED:
            # TODO: Integrate with actual SMS service (Twilio, SNS, etc.)
            pass
        
        return jsonify({
            "message": "SMS notification sent (logged)",
            "to": to_phone
        }), 200
    
    except Exception as e:
        logger.error(f"Failed to send SMS: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/notifications/transaction', methods=['POST'])
def notify_transaction():
    """Send notification about a transaction"""
    try:
        data = request.get_json()
        
        transaction_type = data.get('type')  # deposit, withdrawal, transfer
        amount = data.get('amount')
        user_email = data.get('user_email')
        # 🔧 FIX: לא שולחים account_number בלי validation!
        # account_number = data.get('account_number')  # ❌ Removed
        
        if not all([transaction_type, amount, user_email]):
            return jsonify({"error": "Missing required fields"}), 400
        
        # Create notification message
        if transaction_type == 'deposit':
            subject = "Deposit Confirmation"
            body = f"A deposit of ${amount/100:.2f} was made to your account."
        elif transaction_type == 'withdrawal':
            subject = "Withdrawal Confirmation"
            body = f"A withdrawal of ${amount/100:.2f} was made from your account."
        elif transaction_type == 'transfer':
            subject = "Transfer Confirmation"
            to_account = data.get('to_account_number', 'XXXX')
            body = f"A transfer of ${amount/100:.2f} was initiated. Destination: {to_account[:4]}****"
        else:
            return jsonify({"error": "Invalid transaction type"}), 400
        
        # Log the notification
        logger.info(f"""
        ===== TRANSACTION NOTIFICATION =====
        Type: {transaction_type}
        Amount: ${amount/100:.2f}
        To: {user_email}
        Timestamp: {datetime.now().isoformat()}
        ====================================
        """)
        
        if EMAIL_ENABLED:
            # TODO: Send actual email
            pass
        
        return jsonify({
            "message": "Transaction notification sent",
            "type": transaction_type,
            "to": user_email
        }), 200
    
    except Exception as e:
        logger.error(f"Failed to send transaction notification: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/notifications/welcome', methods=['POST'])
def send_welcome():
    """Send welcome email to new user"""
    try:
        data = request.get_json()
        
        user_email = data.get('email')
        first_name = data.get('first_name')
        
        if not all([user_email, first_name]):
            return jsonify({"error": "Missing required fields"}), 400
        
        subject = "Welcome to Our Banking Service!"
        body = f"""
        Hi {first_name},
        
        Welcome to our banking service! Your account has been successfully created.
        
        You can now:
        - Create bank accounts
        - Make deposits and withdrawals
        - Transfer money between accounts
        
        Thank you for choosing us!
        
        Best regards,
        The Banking Team
        """
        
        logger.info(f"""
        ===== WELCOME EMAIL =====
        To: {user_email}
        Name: {first_name}
        Timestamp: {datetime.now().isoformat()}
        =========================
        """)
        
        if EMAIL_ENABLED:
            # TODO: Send actual email
            pass
        
        return jsonify({
            "message": "Welcome email sent",
            "to": user_email
        }), 200
    
    except Exception as e:
        logger.error(f"Failed to send welcome email: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    # 🎯 השתמש ב-PORT מה-environment!
    app.run(debug=True, host='0.0.0.0', port=SERVICE_PORT)