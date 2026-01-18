from functools import wraps
from flask import g, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
import os

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:example@localhost:5432/mydatabase')

def get_user_role(user_id):
    """
    Get user role from database
    
    Args:
        user_id (str): User ID
    
    Returns:
        str: User role ('admin', 'user', 'viewer') or None
    """
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT role FROM users WHERE id = %s",
            (user_id,)
        )
        
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        return result['role'] if result else None
    
    except Exception as e:
        print(f"Error fetching user role: {e}")
        return None

def require_role(*allowed_roles):
    """
    Decorator to require specific roles for an endpoint
    
    Usage:
        @require_role('admin')
        @require_role('admin', 'user')
    
    Args:
        allowed_roles: Roles that are allowed to access this endpoint
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # user_id should be available from @require_auth
            user_id = g.get('user_id')
            
            if not user_id:
                return jsonify({"error": "Unauthorized"}), 401
            
            # Get user role
            user_role = get_user_role(user_id)
            
            if not user_role:
                return jsonify({"error": "User not found"}), 404
            
            # Check if user has required role
            if user_role not in allowed_roles:
                return jsonify({
                    "error": "Forbidden",
                    "message": f"This action requires one of the following roles: {', '.join(allowed_roles)}",
                    "your_role": user_role
                }), 403
            
            # Store role in g for use in the endpoint
            g.user_role = user_role
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator

def is_admin():
    """
    Check if current user is admin
    
    Returns:
        bool: True if admin, False otherwise
    """
    return g.get('user_role') == 'admin'

def is_viewer():
    """
    Check if current user is viewer
    
    Returns:
        bool: True if viewer, False otherwise
    """
    return g.get('user_role') == 'viewer'

def can_modify():
    """
    Check if current user can modify data (not a viewer)
    
    Returns:
        bool: True if can modify, False if viewer
    """
    return g.get('user_role') in ['admin', 'user']