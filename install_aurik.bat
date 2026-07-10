@echo off
REM Aurik - One-Click Installer (Windows)
echo.
echo ============================================
echo   Aurik - Audio Restoration Setup
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.10+ not found. Please install from python.org
    pause
    exit /b 1
)
echo [OK] Python found

REM Create venv
echo Creating virtual environment...
python -m venv .venv_aurik
echo [OK] Virtual environment created

REM Install dependencies
echo Installing dependencies...
.venv_aurik\Scripts\pip install --upgrade pip -q
.venv_aurik\Scripts\pip install PyQt5 numpy soundfile scipy psutil -q
echo [OK] Dependencies installed

REM Create Start Menu shortcut
echo Creating Start Menu shortcut...
powershell -Command "=(New-Object -COM WScript.Shell).CreateShortcut('%APPDATA%\Microsoft\Windows\Start Menu\Programs\Aurik.lnk'); .TargetPath='%~dp0run_aurik.bat'; .WorkingDirectory='%~dp0'; .Save()"
echo [OK] Shortcut created

echo.
echo Aurik installation complete! Start from the Start Menu.
echo You can also double-click run_aurik.bat in this folder.
pause
