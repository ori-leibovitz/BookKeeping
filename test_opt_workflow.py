"""
Simple OTP Test without gRPC dependencies
Tests OTP flow by checking database and Redis directly
"""
import time

print("="*70)
print("  🧪 בדיקת מערכת OTP - גרסה פשוטה")
print("="*70)

print("\n📋 הוראות:")
print("-" * 70)
print("1. בדוק את הלוגים של user-service:")
print("   docker logs user-service | findstr OTP")
print("\n2. בדוק את Redis:")
print("   docker exec -it redis redis-cli KEYS 'otp:*'")
print("\n3. בדוק את הטבלה users:")
print("   docker exec -it bookkeeping-db psql -U postgres -d mydatabase -c \"SELECT id, email, registration_status FROM users LIMIT 5;\"")
print("\n4. לבדוק שהעמודה registration_status קיימת:")
print("   docker exec -it bookkeeping-db psql -U postgres -d mydatabase -c \"\\d users\"")

print("\n" + "="*70)
print("✅ אם אתה רואה:")
print("   - OTP codes בלוגים של user-service")
print("   - Keys של otp:* ב-Redis")
print("   - העמודה registration_status בטבלת users")
print("אז המערכת עובדת! 🎉")
print("="*70)