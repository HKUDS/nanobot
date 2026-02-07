@echo off
set "DATA_DIR=%~dp0data"

echo ==================================================
echo   Starting Nanobot in PORTABLE MODE
echo   Data Directory: %DATA_DIR%
echo ==================================================

if not exist "%DATA_DIR%" (
    echo [Setup] Creating data directory...
    mkdir "%DATA_DIR%"
)

echo [Docker] Launching container in background...
docker compose -f docker-compose.yml up --build -d

echo.
echo [Success] Nanobot is running in the background.
echo.
echo To view logs:  docker compose logs -f
echo To stop:       docker compose down
echo.
pause
