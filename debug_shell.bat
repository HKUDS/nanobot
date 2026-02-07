@echo off
echo ==================================================
echo   Nanobot Debug Shell (Dev Mode)
echo ==================================================
echo.
echo Opening bash shell in 'nanobot_dev' container...
echo.

docker exec -it nanobot_dev /bin/bash

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [Error] Could not connect. Is 'start_dev.bat' running?
    echo.
    pause
)
