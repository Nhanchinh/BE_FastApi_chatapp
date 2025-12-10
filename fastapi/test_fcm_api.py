"""
Test FCM API endpoint directly
Run: python -m test_fcm_api
"""
import requests
import json

# Configuration
BASE_URL = "http://localhost:8000"
TEST_USERNAME = "tuyen@gmail.com"  # Using real account
TEST_PASSWORD = "123456"

def test_fcm_api():
    print("🧪 Testing FCM API...")
    print(f"📧 Using account: {TEST_USERNAME}")
    print()
    
    # Step 1: Login to get token
    print("1️⃣ Login to get auth token...")
    try:
        login_response = requests.post(
            f"{BASE_URL}/auth/login",
            data={  # FastAPI uses form data for login
                "username": TEST_USERNAME,
                "password": TEST_PASSWORD
            }
        )
        login_response.raise_for_status()
        auth_data = login_response.json()
        auth_token = auth_data["access_token"]
        print(f"✅ Login successful")
        print(f"   Token: {auth_token[:30]}...")
    except requests.exceptions.HTTPError as e:
        print(f"❌ Login failed: {e}")
        print(f"   Status: {e.response.status_code}")
        print(f"   Response: {e.response.text}")
        return
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return
    
    print()
    
    # Step 2: Register FCM token
    print("2️⃣ Register FCM token...")
    test_fcm_token = "test_fcm_token_123abc456def789ghi"
    test_device_id = "test_device_android_001"
    
    try:
        fcm_response = requests.post(
            f"{BASE_URL}/fcm/token",
            headers={
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json"
            },
            json={
                "fcm_token": test_fcm_token,
                "device_id": test_device_id,
                "device_type": "android"
            }
        )
        fcm_response.raise_for_status()
        fcm_data = fcm_response.json()
        print(f"✅ FCM token registered!")
        print(f"   Response: {json.dumps(fcm_data, indent=2)}")
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
        print(f"   Status code: {e.response.status_code}")
        print(f"   Response: {e.response.text}")
        return
    except Exception as e:
        print(f"❌ Failed to register FCM token: {e}")
        return
    
    print()
    
    # Step 3: Verify in database (manual step)
    print("3️⃣ Verify in MongoDB:")
    print("   Run this command:")
    print("   mongo")
    print("   use chatapp")
    print("   db.fcm_tokens.find().pretty()")
    print()
    print("   You should see:")
    print(f'   {{ "user_id": "...", "fcm_token": "{test_fcm_token}", ... }}')
    print()
    
    # Step 4: Send test notification
    print("4️⃣ Send test notification...")
    try:
        notif_response = requests.post(
            f"{BASE_URL}/test/send-notification",
            json={
                "fcm_token": test_fcm_token,
                "title": "Test Notification",
                "body": "Hello from FCM test!",
                "conversation_id": "test123"
            }
        )
        notif_response.raise_for_status()
        notif_data = notif_response.json()
        print(f"✅ Notification sent!")
        print(f"   Response: {json.dumps(notif_data, indent=2)}")
    except Exception as e:
        print(f"⚠️  Could not send test notification: {e}")
        print("   (This is OK if Firebase is not configured)")
    
    print()
    print("✅ Test completed!")

if __name__ == "__main__":
    test_fcm_api()

