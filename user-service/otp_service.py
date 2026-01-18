import random
import string
import redis
import os
import logging

logger = logging.getLogger(__name__)

# Redis configuration
REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))

# OTP configuration
OTP_LENGTH = 6
OTP_EXPIRY = 600  # 10 minutes
MAX_OTP_ATTEMPTS = 3

# Redis client
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def generate_otp():
    """
    Generate a 6-digit OTP code
    
    Returns:
        str: 6-digit code
    """
    return ''.join(random.choices(string.digits, k=OTP_LENGTH))

def store_otp(user_id, otp_code):
    """
    Store OTP in Redis with expiry
    
    Args:
        user_id (str): User ID
        otp_code (str): OTP code to store
    
    Returns:
        bool: True if successful
    """
    try:
        # Store OTP with TTL
        redis_client.setex(
            f"otp:{user_id}",
            OTP_EXPIRY,
            otp_code
        )
        
        # Reset attempt counter
        redis_client.setex(
            f"otp_attempts:{user_id}",
            OTP_EXPIRY,
            0
        )
        
        logger.info(f"OTP stored for user {user_id}, expires in {OTP_EXPIRY}s")
        return True
    
    except Exception as e:
        logger.error(f"Failed to store OTP: {e}")
        return False

def verify_otp(user_id, provided_otp):
    """
    Verify OTP code
    
    Args:
        user_id (str): User ID
        provided_otp (str): OTP code provided by user
    
    Returns:
        dict: {
            'valid': bool,
            'message': str,
            'attempts_left': int or None
        }
    """
    try:
        # Check if OTP exists
        stored_otp = redis_client.get(f"otp:{user_id}")
        
        if not stored_otp:
            return {
                'valid': False,
                'message': 'OTP expired or not found',
                'attempts_left': None
            }
        
        # Get current attempt count
        attempts = redis_client.get(f"otp_attempts:{user_id}")
        attempts = int(attempts) if attempts else 0
        
        # Check if blocked
        if attempts >= MAX_OTP_ATTEMPTS:
            return {
                'valid': False,
                'message': 'Too many failed attempts. Please request a new OTP.',
                'attempts_left': 0
            }
        
        # Verify OTP
        if provided_otp == stored_otp:
            # Success! Delete OTP
            redis_client.delete(f"otp:{user_id}")
            redis_client.delete(f"otp_attempts:{user_id}")
            
            logger.info(f"OTP verified successfully for user {user_id}")
            return {
                'valid': True,
                'message': 'OTP verified successfully',
                'attempts_left': None
            }
        else:
            # Wrong OTP, increment attempts
            attempts += 1
            redis_client.set(f"otp_attempts:{user_id}", attempts)
            redis_client.expire(f"otp_attempts:{user_id}", OTP_EXPIRY)
            
            attempts_left = MAX_OTP_ATTEMPTS - attempts
            
            logger.warning(f"Invalid OTP for user {user_id}. Attempts: {attempts}/{MAX_OTP_ATTEMPTS}")
            
            return {
                'valid': False,
                'message': f'Invalid OTP. {attempts_left} attempts remaining.',
                'attempts_left': attempts_left
            }
    
    except Exception as e:
        logger.error(f"Failed to verify OTP: {e}")
        return {
            'valid': False,
            'message': 'Internal error',
            'attempts_left': None
        }

def get_otp_status(user_id):
    """
    Get OTP status for user
    
    Args:
        user_id (str): User ID
    
    Returns:
        dict: {
            'exists': bool,
            'ttl': int (seconds remaining),
            'attempts': int
        }
    """
    try:
        otp_exists = redis_client.exists(f"otp:{user_id}")
        ttl = redis_client.ttl(f"otp:{user_id}") if otp_exists else 0
        attempts = redis_client.get(f"otp_attempts:{user_id}")
        attempts = int(attempts) if attempts else 0
        
        return {
            'exists': bool(otp_exists),
            'ttl': ttl,
            'attempts': attempts,
            'max_attempts': MAX_OTP_ATTEMPTS
        }
    
    except Exception as e:
        logger.error(f"Failed to get OTP status: {e}")
        return {
            'exists': False,
            'ttl': 0,
            'attempts': 0,
            'max_attempts': MAX_OTP_ATTEMPTS
        }

def delete_otp(user_id):
    """
    Delete OTP for user
    
    Args:
        user_id (str): User ID
    
    Returns:
        bool: True if successful
    """
    try:
        redis_client.delete(f"otp:{user_id}")
        redis_client.delete(f"otp_attempts:{user_id}")
        logger.info(f"OTP deleted for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete OTP: {e}")
        return False