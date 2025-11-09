# Chat App Backend - Setup Guide

Backend API cho ứng dụng chat real-time với FastAPI, MongoDB và Redis.

## Yêu cầu

- Python 3.10+
- MongoDB 4.4+
- Redis 6.0+ (optional - cho online status)

## Cài đặt

### 1. Clone repository và vào thư mục

```bash
cd BE/fastapi
```

### 2. Tạo virtual environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python -m venv venv
source venv/bin/activate
```

### 3. Cài đặt dependencies

```bash
pip install -r requirements.txt
```

### 4. Cấu hình MongoDB

**Option 1: Local MongoDB**
```bash
# Cài đặt và chạy MongoDB
mongod
```
**Option 1.5: Atlas MongoDB**
sửa tạo file .env chứa các biến như mục 6 là đc.

**Option 2: Docker**
```bash
docker run -d -p 27017:27017 --name mongodb mongo:latest
```

### 5. Cấu hình Redis (Optional)

**Option 1: Local Redis**
```bash
redis-server
```

**Option 2: Docker**
```bash
docker run -d -p 6379:6379 --name redis redis:latest
```

### 6. Tạo file `.env`

Tạo file `.env` trong thư mục `BE/fastapi/`:

```env
# MongoDB
MONGO_URL=mongodb://localhost:27017      //cái này phải thay đúng link trên atlas mongodb 
DB_NAME=chatapp_db

# JWT
JWT_SECRET_KEY=your-secret-key-change-this
JWT_ALGORITHM=HS256
JWT_EXPIRES_MINUTES=60

# Redis (Optional - cho online status)
REDIS_URL=redis://localhost:6379

# FCM (Optional - cho push notifications)
FCM_SERVER_KEY=your-fcm-server-key
```

### 7. Chạy ứng dụng

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Server sẽ chạy tại: `http://localhost:8000`

## API Documentation

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Lưu ý

- Nếu không có Redis, app vẫn chạy bình thường nhưng không có online status
- Đổi `JWT_SECRET_KEY` thành giá trị random mạnh trong production
- MongoDB và Redis phải chạy trước khi start app

