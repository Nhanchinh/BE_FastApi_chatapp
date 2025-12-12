"""
Script to test FCM token storage directly
Run: python -m test_fcm_db
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime

async def test_fcm_storage():
    # Connect to MongoDB
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["chatapp"]  # Thay tên database của bạn
    collection = db["fcm_tokens"]
    
    print("🔍 Testing FCM token storage...")
    
    # Test data
    test_token = {
        "user_id": "test_user_123",
        "fcm_token": "test_fcm_token_abc123xyz",
        "device_id": "test_device_android_001",
        "device_type": "android",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "is_active": True
    }
    
    # Insert test token
    result = await collection.insert_one(test_token)
    print(f"✅ Inserted test token with ID: {result.inserted_id}")
    
    # Verify insertion
    found = await collection.find_one({"_id": result.inserted_id})
    if found:
        print(f"✅ Verified: Token exists in DB")
        print(f"   User ID: {found['user_id']}")
        print(f"   FCM Token: {found['fcm_token'][:20]}...")
        print(f"   Device Type: {found['device_type']}")
    else:
        print("❌ ERROR: Token not found after insertion!")
    
    # Count tokens
    count = await collection.count_documents({})
    print(f"\n📊 Total FCM tokens in DB: {count}")
    
    # List all tokens
    print("\n📋 All FCM tokens:")
    async for doc in collection.find().limit(10):
        print(f"   - User: {doc['user_id']}, Device: {doc.get('device_id', 'N/A')}, Active: {doc.get('is_active', True)}")
    
    # Clean up test token
    await collection.delete_one({"_id": result.inserted_id})
    print(f"\n🗑️  Cleaned up test token")
    
    client.close()
    print("\n✅ Test completed!")

if __name__ == "__main__":
    asyncio.run(test_fcm_storage())



