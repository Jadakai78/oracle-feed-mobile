@echo off
cd /d "C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba\refresh_kraken_spot_speed_review_v1.ps1"
exit /b %ERRORLEVEL%
