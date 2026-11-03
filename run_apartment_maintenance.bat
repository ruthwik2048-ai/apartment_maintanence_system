@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Project virtual environment not found.
    echo Run the setup instructions in README.md first.
    pause
    exit /b 1
)

echo Checking whether the website is already running...
powershell -NoProfile -Command "$request = [System.Net.WebRequest]::Create('http://127.0.0.1:8000/'); $request.Timeout = 2000; try { $response = $request.GetResponse(); $response.Close(); exit 0 } catch { exit 1 }"
if not errorlevel 1 (
    echo The website is already running. Opening it in your browser.
    start "" "http://127.0.0.1:8000/"
    pause
    exit /b 0
)

echo Starting Vijetha Nivas at http://127.0.0.1:8000/
echo Keep this window open while using the website.
echo Press Ctrl+C to stop the server.
echo.

start "" /b powershell -NoProfile -Command "$deadline = (Get-Date).AddSeconds(45); while ((Get-Date) -lt $deadline) { try { $request = [System.Net.WebRequest]::Create('http://127.0.0.1:8000/'); $request.Timeout = 2000; $response = $request.GetResponse(); $response.Close(); Write-Output 'Website is ready; opening the default browser.'; Start-Process 'http://127.0.0.1:8000/'; exit 0 } catch { }; Start-Sleep -Milliseconds 500 }; Write-Error 'The website did not become available within 45 seconds.'; exit 1"
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000

if errorlevel 1 (
    echo.
    echo The website server stopped with an error.
    pause
)

endlocal
