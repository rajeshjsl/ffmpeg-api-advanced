@echo off
setlocal

:: Set environment variables for localhost
set CELERY_BROKER_URL=redis://localhost:6379/0
set CELERY_RESULT_BACKEND=redis://localhost:6379/0
set FFMPEG_TIMEOUT=0
set FFMPEG_THREADS=auto
set KEEP_FILES=false
set CLEANUP_INTERVAL=3600
set FILE_RETENTION_PERIOD=86400

:: Create a unique name for our Redis container
set REDIS_CONTAINER_NAME=ffmpeg-api-redis-dev

echo Starting development environment...

:: Start Redis container
echo Starting Redis...
docker rm -f %REDIS_CONTAINER_NAME% 2>nul
docker run --name %REDIS_CONTAINER_NAME% -d -p 6379:6379 redis:alpine
if errorlevel 1 (
    echo Failed to start Redis container
    goto cleanup
)

:: Start Flask in background
echo Starting Flask API...
start "Flask API" cmd /c "python -m flask run --host=0.0.0.0 --port=8000"

:: Start Celery in background
echo Starting Celery worker...
start "Celery Worker" cmd /c "celery -A app.celery worker --loglevel=info"

echo.
echo Development environment is running
echo - Redis: localhost:6379
echo - Flask API: http://localhost:8000
echo - Celery worker is active
echo.
echo Press Ctrl+C to stop all services...
echo.

:: Wait for Ctrl+C
pause > nul

:cleanup
:: Cleanup
echo.
echo Cleaning up...

:: Stop Redis container
docker stop %REDIS_CONTAINER_NAME%
docker rm %REDIS_CONTAINER_NAME%

:: Kill Flask and Celery processes
taskkill /FI "WindowTitle eq Flask API*" /F
taskkill /FI "WindowTitle eq Celery Worker*" /F
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Flask API*"
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Celery Worker*"

echo.
echo Development environment stopped
echo.

endlocal