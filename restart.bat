@echo off
echo Restarting nanobot container (code will reload)...
docker-compose -f docker-compose.yml -f docker-compose.dev.yml restart
echo Done! Check start_dev.bat terminal for logs.
