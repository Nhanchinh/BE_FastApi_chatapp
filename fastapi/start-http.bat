@echo off
echo ========================================
echo   DEMO HTTP (NO SSL) + NGROK
echo   Running on Port 8000
echo ========================================
echo.

:: Kích hoạt venv
call venv\Scripts\activate.bat

:: Chạy server HTTP (Port 8000, không SSL)
start "HTTP SERVER" cmd /k "call venv\Scripts\activate.bat && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

:: Đợi 3 giây
timeout /t 3 >nul

:: Chạy ngrok
start "NGROK TUNNEL" cmd /k "ngrok http 8000"

echo.
echo XONG! 
echo - Cho ngrok hien link
echo - Truy cap: http://[link].ngrok-free.app
echo.
pause
