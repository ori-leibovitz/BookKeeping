# auth_middleware.py
from functools import wraps
from flask import request, jsonify, g
import jwt
import os

JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'dev-secret-key')

def verify_token(token):
    """
    Verify JWT token and return user_id
    
    Args:
        token (str): JWT token
    
    Returns:
        str: user_id if valid, None otherwise
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])
        return payload.get('user_id')
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception:
        return None

def require_auth(f):
    """
    Decorator to require authentication for routes
    
    Usage:
        @app.route('/some-endpoint')
        @require_auth
        def some_endpoint():
            user_id = g.user_id  # Available here!
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get Authorization header
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({"error": "Unauthorized", "message": "No authorization header"}), 401
        
        if not auth_header.startswith('Bearer '):
            return jsonify({"error": "Unauthorized", "message": "Invalid authorization format"}), 401
        
        # Extract token
        try:
            token = auth_header.split(' ')[1]
        except IndexError:
            return jsonify({"error": "Unauthorized", "message": "Invalid token format"}), 401
        
        # Verify token
        user_id = verify_token(token)
        
        if not user_id:
            return jsonify({"error": "Unauthorized", "message": "Invalid or expired token"}), 401
        
        # Store user_id in Flask's g object (available during request)
        g.user_id = user_id
        
        # Call the original function
        return f(*args, **kwargs)
    
    return decorated_function

def optional_auth(f):
    """
    Decorator for optional authentication
    Sets g.user_id if token is valid, otherwise None
    
    Usage:
        @app.route('/some-public-endpoint')
        @optional_auth
        def some_endpoint():
            if g.user_id:
                # Authenticated user
            else:
                # Anonymous user
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if auth_header and auth_header.startswith('Bearer '):
            try:
                token = auth_header.split(' ')[1]
                g.user_id = verify_token(token)
            except:
                g.user_id = None
        else:
            g.user_id = None
        
        return f(*args, **kwargs)
    
    return decorated_function