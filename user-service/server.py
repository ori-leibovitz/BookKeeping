import grpc
from concurrent import futures
import time
import uuid
import bcrypt
import jwt
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import logging

# Import OTP service
from otp_service import generate_otp, store_otp, verify_otp, get_otp_status, delete_otp

# Import generated gRPC code
import user_service_pb2
import user_service_pb2_grpc

# Configuration
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:example@localhost:5432/mydatabase')
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'my-super-secret-jwt-key-2024')
SERVICE_PORT = int(os.environ.get('SERVICE_PORT', 5001))

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

class UserService(user_service_pb2_grpc.UserServiceServicer):
    
    def CreateUser(self, request, context):
        """
        Create a new user (Registration)
        Status will be 'pending' until OTP is verified
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check if user already exists
            cursor.execute(
                "SELECT id FROM users WHERE email = %s",
                (request.email,)
            )
            existing_user = cursor.fetchone()
            
            if existing_user:
                context.set_code(grpc.StatusCode.ALREADY_EXISTS)
                context.set_details('User with this email already exists')
                return user_service_pb2.CreateUserResponse()
            
            # Hash password
            password_hash = bcrypt.hashpw(
                request.password.encode('utf-8'),
                bcrypt.gensalt()
            ).decode('utf-8')
            
            # Generate user ID
            user_id = str(uuid.uuid4())
            
            # Insert user with 'pending' status
            cursor.execute(
                """
                INSERT INTO users 
                (id, first_name, last_name, email, password, registration_status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    request.first_name,
                    request.last_name,
                    request.email,
                    password_hash,
                    datetime.now(),
                    datetime.now()
                )
            )
            
            conn.commit()
            
            # Generate and store OTP
            otp_code = generate_otp()
            store_otp(user_id, otp_code)
            
            # TODO: Send OTP via email (for now, just log it)
            logger.info(f"🔐 OTP for {request.email}: {otp_code}")
            logger.info(f"User {user_id} created with status 'pending'")
            
            cursor.close()
            conn.close()
            
            return user_service_pb2.CreateUserResponse(
                id=user_id,
                message=f"User created. OTP sent to email. (Dev: OTP is {otp_code})"
            )
        
        except Exception as e:
            logger.error(f"Failed to create user: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f'Failed to create user: {str(e)}')
            return user_service_pb2.CreateUserResponse()
    
    def VerifyOTP(self, request, context):
        """
        Verify OTP and activate user account
        """
        try:
            # Verify OTP
            result = verify_otp(request.user_id, request.otp_code)
            
            if not result['valid']:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(result['message'])
                return user_service_pb2.VerifyOTPResponse(
                    success=False,
                    message=result['message'],
                    attempts_left=result.get('attempts_left', 0)
                )
            
            # OTP is valid - update user status to 'confirmed'
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                """
                UPDATE users 
                SET registration_status = 'confirmed', updated_at = %s
                WHERE id = %s
                """,
                (datetime.now(), request.user_id)
            )
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"User {request.user_id} verified and activated")
            
            return user_service_pb2.VerifyOTPResponse(
                success=True,
                message="Account verified successfully! You can now login.",
                attempts_left=0
            )
        
        except Exception as e:
            logger.error(f"Failed to verify OTP: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f'Failed to verify OTP: {str(e)}')
            return user_service_pb2.VerifyOTPResponse(
                success=False,
                message="Internal error"
            )
    
    def ResendOTP(self, request, context):
        """
        Resend OTP to user
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check if user exists and is pending
            cursor.execute(
                "SELECT id, email, registration_status FROM users WHERE id = %s",
                (request.user_id,)
            )
            user = cursor.fetchone()
            
            if not user:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details('User not found')
                return user_service_pb2.ResendOTPResponse(success=False)
            
            if user['registration_status'] == 'confirmed':
                context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                context.set_details('User already verified')
                return user_service_pb2.ResendOTPResponse(success=False)
            
            # Delete old OTP
            delete_otp(request.user_id)
            
            # Generate new OTP
            otp_code = generate_otp()
            store_otp(request.user_id, otp_code)
            
            # TODO: Send OTP via email
            logger.info(f"🔐 New OTP for {user['email']}: {otp_code}")
            
            cursor.close()
            conn.close()
            
            return user_service_pb2.ResendOTPResponse(
                success=True,
                message=f"New OTP sent. (Dev: OTP is {otp_code})"
            )
        
        except Exception as e:
            logger.error(f"Failed to resend OTP: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f'Failed to resend OTP: {str(e)}')
            return user_service_pb2.ResendOTPResponse(success=False)
    
    def LoginUser(self, request, context):
        """
        Login user (only if status is 'confirmed')
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT id, password, registration_status FROM users WHERE email = %s",
                (request.email,)
            )
            user = cursor.fetchone()
            
            if not user:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details('Invalid credentials')
                return user_service_pb2.LoginUserResponse()
            
            # Check if user is confirmed
            if user['registration_status'] != 'confirmed':
                context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                context.set_details('Account not verified. Please verify your OTP first.')
                return user_service_pb2.LoginUserResponse()
            
            # Verify password
            if not bcrypt.checkpw(request.password.encode('utf-8'), user['password'].encode('utf-8')):
                context.set_code(grpc.StatusCode.UNAUTHENTICATED)
                context.set_details('Invalid credentials')
                return user_service_pb2.LoginUserResponse()
            
            # Generate JWT token
            token = jwt.encode(
                {
                    'user_id': user['id'],
                    'email': request.email,
                    'exp': datetime.utcnow() + timedelta(hours=24)
                },
                JWT_SECRET_KEY,
                algorithm='HS256'
            )
            
            cursor.close()
            conn.close()
            
            logger.info(f"User {user['id']} logged in successfully")
            
            return user_service_pb2.LoginUserResponse(
                token=token,
                user_id=user['id']
            )
        
        except Exception as e:
            logger.error(f"Login failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details('Login failed')
            return user_service_pb2.LoginUserResponse()
    
    def VerifyToken(self, request, context):
        """
        Verify JWT token
        """
        try:
            payload = jwt.decode(
                request.token,
                JWT_SECRET_KEY,
                algorithms=['HS256']
            )
            
            return user_service_pb2.VerifyTokenResponse(
                valid=True,
                user_id=payload['user_id'],
                email=payload['email']
            )
        
        except jwt.ExpiredSignatureError:
            return user_service_pb2.VerifyTokenResponse(
                valid=False,
                user_id='',
                email=''
            )
        except jwt.InvalidTokenError:
            return user_service_pb2.VerifyTokenResponse(
                valid=False,
                user_id='',
                email=''
            )

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    user_service_pb2_grpc.add_UserServiceServicer_to_server(
        UserService(), server
    )
    server.add_insecure_port(f'[::]:{SERVICE_PORT}')
    server.start()
    logger.info(f"User Service (gRPC) running on port {SERVICE_PORT}")
    
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        server.stop(0)

if __name__ == '__main__':
    serve()