@echo off
echo ==================================================
echo   Nanobot Interactive Chat (Dev Mode)
echo ==================================================
echo.
echo Connecting to running 'nanobot_dev' container...
echo Note: 'start_dev.bat' must be running in another window.
echo.

docker exec -it nanobot_dev nanobot agent --session cli:dev

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [Error] Could not connect. Is 'start_dev.bat' running?
    echo.
    pause
)
