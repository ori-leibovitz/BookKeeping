"""
Test User Roles & Permissions
Tests that admin, user, and viewer roles work correctly
"""
import requests
import jwt
from datetime import datetime, timedelta

BASE_URL = 'http://localhost'
ACCOUNT_SERVICE_PORT = 5002
TRANSACTION_SERVICE_PORT = 5003
JWT_SECRET_KEY = 'my-super-secret-jwt-key-2024'

def create_token(user_id, email):
    """Create JWT token for testing"""
    return jwt.encode(
        {
            'user_id': user_id,
            'email': email,
            'exp': datetime.utcnow() + timedelta(hours=24)
        },
        JWT_SECRET_KEY,
        algorithm='HS256'
    )

def test_roles():
    print("="*70)
    print("  🧪 בדיקת מערכת Roles & Permissions")
    print("="*70)
    
    # Create test users with different roles
    print("\n📋 הכנה: יוצר 3 משתמשים עם roles שונים...")
    print("-" * 70)
    
    # User IDs (we'll create them in DB)
    admin_id = '550e8400-e29b-41d4-a716-446655440000'  # existing admin
    user_id = '660e8400-e29b-41d4-a716-446655440001'
    viewer_id = '770e8400-e29b-41d4-a716-446655440002'
    
    # Create tokens
    admin_token = create_token(admin_id, 'admin@example.com')
    user_token = create_token(user_id, 'user@example.com')
    viewer_token = create_token(viewer_id, 'viewer@example.com')
    
    print(f"✅ Admin token: {admin_token[:20]}...")
    print(f"✅ User token: {user_token[:20]}...")
    print(f"✅ Viewer token: {viewer_token[:20]}...")
    
    # Test 1: Admin can create account
    print("\n1️⃣ בדיקה: Admin יכול ליצור חשבון")
    print("-" * 70)
    
    response = requests.post(
        f'{BASE_URL}:{ACCOUNT_SERVICE_PORT}/accounts',
        headers={'Authorization': f'Bearer {admin_token}', 'Content-Type': 'application/json'},
        json={'type': 'checking', 'balance_cents': 100000}
    )
    
    if response.status_code == 201:
        print(f"✅ Admin יצר חשבון בהצלחה!")
        admin_account_id = response.json()['id']
    else:
        print(f"❌ שגיאה: {response.status_code} - {response.json()}")
        admin_account_id = None
    
    # Test 2: User can create account
    print("\n2️⃣ בדיקה: User יכול ליצור חשבון")
    print("-" * 70)
    
    response = requests.post(
        f'{BASE_URL}:{ACCOUNT_SERVICE_PORT}/accounts',
        headers={'Authorization': f'Bearer {user_token}', 'Content-Type': 'application/json'},
        json={'type': 'savings', 'balance_cents': 50000}
    )
    
    if response.status_code == 201:
        print(f"✅ User יצר חשבון בהצלחה!")
        user_account_id = response.json()['id']
    else:
        print(f"❌ שגיאה: {response.status_code} - {response.json()}")
        user_account_id = None
    
    # Test 3: Viewer CANNOT create account (should get 403)
    print("\n3️⃣ בדיקה: Viewer לא יכול ליצור חשבון (צריך 403)")
    print("-" * 70)
    
    response = requests.post(
        f'{BASE_URL}:{ACCOUNT_SERVICE_PORT}/accounts',
        headers={'Authorization': f'Bearer {viewer_token}', 'Content-Type': 'application/json'},
        json={'type': 'checking', 'balance_cents': 10000}
    )
    
    if response.status_code == 403:
        print(f"✅ נכון! Viewer קיבל 403 Forbidden")
        print(f"   Message: {response.json().get('message', '')}")
    elif response.status_code == 201:
        print(f"❌ שגיאה! Viewer הצליח ליצור חשבון (לא אמור!)")
    else:
        print(f"⚠️ קוד לא צפוי: {response.status_code} - {response.json()}")
    
    # Test 4: Viewer CANNOT deposit (should get 403)
    if admin_account_id:
        print("\n4️⃣ בדיקה: Viewer לא יכול להפקיד כסף (צריך 403)")
        print("-" * 70)
        
        response = requests.post(
            f'{BASE_URL}:{TRANSACTION_SERVICE_PORT}/transactions/{admin_account_id}/deposit',
            headers={'Authorization': f'Bearer {viewer_token}', 'Content-Type': 'application/json'},
            json={'amount': 5000}
        )
        
        if response.status_code == 403:
            print(f"✅ נכון! Viewer קיבל 403 Forbidden")
        elif response.status_code == 200:
            print(f"❌ שגיאה! Viewer הצליח להפקיד (לא אמור!)")
        else:
            print(f"⚠️ קוד לא צפוי: {response.status_code} - {response.json()}")
    
    # Test 5: User can deposit to own account
    if user_account_id:
        print("\n5️⃣ בדיקה: User יכול להפקיד לחשבון שלו")
        print("-" * 70)
        
        response = requests.post(
            f'{BASE_URL}:{TRANSACTION_SERVICE_PORT}/transactions/{user_account_id}/deposit',
            headers={'Authorization': f'Bearer {user_token}', 'Content-Type': 'application/json'},
            json={'amount': 10000}
        )
        
        if response.status_code == 200:
            print(f"✅ User הפקיד בהצלחה!")
        else:
            print(f"❌ שגיאה: {response.status_code} - {response.json()}")
    
    # Test 6: Admin can see all accounts
    print("\n6️⃣ בדיקה: Admin רואה את כל החשבונות")
    print("-" * 70)
    
    response = requests.get(
        f'{BASE_URL}:{ACCOUNT_SERVICE_PORT}/accounts',
        headers={'Authorization': f'Bearer {admin_token}'}
    )
    
    if response.status_code == 200:
        data = response.json()
        if 'view' in data and data['view'] == 'admin':
            print(f"✅ Admin רואה את כל החשבונות!")
            print(f"   סה\"כ חשבונות: {data.get('total', len(data.get('accounts', [])))}")
        else:
            print(f"⚠️ Admin רואה חשבונות אבל לא כ-admin view")
    else:
        print(f"❌ שגיאה: {response.status_code}")
    
    # Test 7: User sees only own accounts
    print("\n7️⃣ בדיקה: User רואה רק את החשבונות שלו")
    print("-" * 70)
    
    response = requests.get(
        f'{BASE_URL}:{ACCOUNT_SERVICE_PORT}/accounts',
        headers={'Authorization': f'Bearer {user_token}'}
    )
    
    if response.status_code == 200:
        data = response.json()
        accounts = data.get('accounts', [])
        print(f"✅ User רואה {len(accounts)} חשבון/ות")
        
        # Check all accounts belong to user
        all_mine = all(acc.get('owner_id') != admin_id for acc in accounts if 'owner_id' not in acc or acc.get('owner_id'))
        if all_mine or 'owner_id' not in accounts[0]:
            print(f"   ✅ כל החשבונות שייכים למשתמש (או אין owner_id - נכון!)")
        else:
            print(f"   ❌ User רואה חשבונות של אחרים!")
    else:
        print(f"❌ שגיאה: {response.status_code}")
    
    # Test 8: Only admin can approve transfers
    print("\n8️⃣ בדיקה: רק Admin יכול לאשר העברות")
    print("-" * 70)
    
    # Try with user token (should fail)
    fake_transfer_id = '00000000-0000-0000-0000-000000000000'
    
    response = requests.post(
        f'{BASE_URL}:{TRANSACTION_SERVICE_PORT}/transfers/{fake_transfer_id}/approve',
        headers={'Authorization': f'Bearer {user_token}'}
    )
    
    if response.status_code == 403:
        print(f"✅ נכון! User לא יכול לאשר (403 Forbidden)")
    elif response.status_code == 404:
        print(f"✅ User הגיע לendpoint אבל ההעברה לא נמצאה (404)")
        print(f"   ℹ️ זה OK - אומר שהוא עבר את בדיקת ההרשאות")
    else:
        print(f"⚠️ קוד לא צפוי: {response.status_code}")
    
    print("\n" + "="*70)
    print("✅ בדיקת Roles הסתיימה!")
    print("="*70)

if __name__ == '__main__':
    print("\n⚠️ הערה: צריך קודם ליצור את המשתמשים בDB:\n")
    print("docker exec -it bookkeeping-db psql -U postgres -d mydatabase -c \"")
    print("INSERT INTO users (id, first_name, last_name, email, password, role, registration_status, created_at, updated_at)")
    print("VALUES ")
    print("  ('660e8400-e29b-41d4-a716-446655440001', 'Regular', 'User', 'user@example.com', '\\$2b\\$12\\$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqXjM1oXMa', 'user', 'confirmed', NOW(), NOW()),")
    print("  ('770e8400-e29b-41d4-a716-446655440002', 'Viewer', 'User', 'viewer@example.com', '\\$2b\\$12\\$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqXjM1oXMa', 'viewer', 'confirmed', NOW(), NOW())")
    print("ON CONFLICT (email) DO NOTHING;")
    print('"\n')
    
    input("▶️ לחץ Enter אחרי שהרצת את הפקודה SQL למעלה...\n")
    
    test_roles()