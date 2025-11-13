@echo off
echo ========================================
echo   DEMO HTTPS THAT - LET'S ENCRYPT + NGROK
echo   Dung chinh file cert.pem + key.pem
echo ========================================
echo.

:: Kích hoạt venv
call venv\Scripts\activate.bat

:: Chạy server HTTPS - DÙNG TÊN FILE THẬT
start "HTTPS SERVER" cmd /k "call venv\Scripts\activate.bat && uvicorn app.main:app --host 0.0.0.0 --port 443 --ssl-keyfile=key.pem --ssl-certfile=cert.pem --reload"

:: Đợi 8 giây
timeout /t 8 >nul

:: Chạy ngrok
start "NGROK TUNNEL" cmd /k "ngrok http 443"

echo.
echo XONG! 
echo - Cho ngrok hien link
echo - Truy cap: https://[link].ngrok-free.app
echo - O KHOA XANH + Let’s Encrypt
echo.
pause