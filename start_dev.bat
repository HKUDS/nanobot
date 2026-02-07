@echo off
echo ==================================================
echo   Starting Nanobot in DEVELOPER MODE (Hot Reload)
echo   Data Directory: %cd%\data
echo   Code Source:    %cd%\nanobot
echo.
echo   USAGE:
echo   - Edit code/config, changes apply on restart
echo   - Press Ctrl+C to stop
echo   - Use 'docker-compose restart' to reload config
echo ==================================================
echo.

docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
