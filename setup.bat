@echo off
echo ==================================================
echo   Nanobot Setup (First Run)
echo ==================================================
echo.
echo [Setup] Creating initial configuration and identity files...
echo.

docker compose -f docker-compose.yml run --rm nanobot onboard

echo.
echo ==================================================
echo   Setup Complete!
echo ==================================================
echo.
echo 1. Go to: c:\blockchain\nanobot\data\config.json
echo 2. Open it and add your API Key (e.g. providers.openrouter.apiKey)
echo 3. Run 'start_dev.bat' or 'start_portable.bat'
echo.
pause
