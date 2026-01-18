# test_error_validation.py
import requests
import jwt
from datetime import datetime, timedelta

# Same config as test_complete_workflow.py
USER_ID = '550e8400-e29b-41d4-a716-446655440000'
JWT_SECRET_KEY = 'my-super-secret-jwt-key-2024'

# Generate token
token = jwt.encode(
    {
        'user_id': USER_ID,
        'email': 'test@example.com',
        'exp': datetime.utcnow() + timedelta(hours=24)
    },
    JWT_SECRET_KEY,
    algorithm='HS256'
)

headers = {
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json'
}

print("🧪 בדיקת Error Handling (400 vs 500)\n")
print("="*60)

# Test 1: Create account with negative balance
print("\n1️⃣ סכום שלילי בחשבון חדש")
print("-" * 60)
response = requests.post(
    'http://localhost:5002/accounts',
    headers=headers,
    json={'type': 'checking', 'balance_cents': -5000}
)
print(f"   Status: {response.status_code}")
print(f"   Response: {response.json()}")
# Expected: Should work (no validation in create_account)
# או 400 אם הוספת validation

# Test 2: Insufficient funds withdrawal
print("\n2️⃣ Insufficient Funds - Withdrawal")
print("-" * 60)

# יצירת חשבון עם $50
acc_response = requests.post(
    'http://localhost:5002/accounts',
    headers=headers,
    json={'type': 'checking', 'balance_cents': 5000}  # $50
)

if acc_response.status_code == 201:
    account_id = acc_response.json()['id']
    print(f"✅ חשבון נוצר: {account_id} עם $50")
    
    # נסה למשוך $100 (יש רק $50)
    withdraw_response = requests.post(
        f'http://localhost:5003/transactions/{account_id}/withdraw',
        headers=headers,
        json={'amount': 10000}  # $100 בcents
    )
    
    print(f"   Status: {withdraw_response.status_code}")
    print(f"   Response: {withdraw_response.json()}")
    
    if withdraw_response.status_code == 400:
        print("   ✅ מצוין! קיבלנו 400 (Bad Request)")
    elif withdraw_response.status_code == 500:
        print("   ❌ בעיה! קיבלנו 500 (Server Error)")
    else:
        print(f"   ⚠️ קיבלנו {withdraw_response.status_code}")

# Test 3: Insufficient funds transfer
print("\n3️⃣ Insufficient Funds - Transfer")
print("-" * 60)

# יצירת חשבון יעד
target_response = requests.post(
    'http://localhost:5002/accounts',
    headers=headers,
    json={'type': 'savings', 'balance_cents': 1000}
)

if acc_response.status_code == 201 and target_response.status_code == 201:
    from_acc = acc_response.json()['id']
    to_acc = target_response.json()['id']
    
    # נסה להעביר $100 (יש רק $50)
    transfer_response = requests.post(
        f'http://localhost:5003/transactions/{from_acc}/transfer',
        headers=headers,
        json={'amount': 10000, 'to_account_id': to_acc}
    )
    
    print(f"   Status: {transfer_response.status_code}")
    print(f"   Response: {transfer_response.json()}")
    
    if transfer_response.status_code == 400:
        print("   ✅ מצוין! קיבלנו 400")
    elif transfer_response.status_code == 500:
        print("   ❌ בעיה! קיבלנו 500")

# Test 4: Invalid amount (negative)
print("\n4️⃣ סכום שלילי בהפקדה")
print("-" * 60)

if acc_response.status_code == 201:
    account_id = acc_response.json()['id']
    
    deposit_response = requests.post(
        f'http://localhost:5003/transactions/{account_id}/deposit',
        headers=headers,
        json={'amount': -1000}
    )
    
    print(f"   Status: {deposit_response.status_code}")
    print(f"   Response: {deposit_response.json()}")
    
    if deposit_response.status_code == 400:
        print("   ✅ מצוין! קיבלנו 400")
    elif deposit_response.status_code == 500:
        print("   ❌ בעיה! קיבלנו 500")

print("\n" + "="*60)
print("✅ בדיקה הסתיימה!")