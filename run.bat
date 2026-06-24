@echo off
title AI Email Agent - Launcher
color 0A

echo ============================================================
echo         AI EMAIL AGENT - Automated Gmail Response System
echo         AI Backend : HuggingFace Inference Router
echo         Email Mode : Gmail Push Notifications (Interrupt)
echo ============================================================
echo.

:: -------------------------------------------------------
:: Step 1: Check Python is installed
:: -------------------------------------------------------
echo [1/6] Checking Python installation...
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Python is NOT installed or not in PATH.
    echo         Please install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python found.
echo.

:: -------------------------------------------------------
:: Step 2: Create virtual environment if it doesn't exist
:: -------------------------------------------------------
echo [2/6] Checking virtual environment...
IF NOT EXIST "venv\Scripts\activate.bat" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    IF ERRORLEVEL 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
) ELSE (
    echo [OK] Virtual environment already exists.
)
echo.

:: -------------------------------------------------------
:: Step 3: Activate venv and install dependencies
:: -------------------------------------------------------
echo [3/6] Activating virtual environment and installing dependencies...
call venv\Scripts\activate.bat

pip install -r requirements.txt --quiet
IF ERRORLEVEL 1 (
    echo [ERROR] Failed to install dependencies. Check your internet connection.
    pause
    exit /b 1
)
echo [OK] All dependencies installed.
echo.

:: -------------------------------------------------------
:: Step 4: Check .env file and credentials.json exist
:: -------------------------------------------------------
echo [4/6] Checking configuration files...

IF NOT EXIST ".env" (
    echo [WARN] .env file not found. Copying from .env.example...
    IF EXIST ".env.example" (
        copy .env.example .env >nul
        echo [INFO] .env created from example. Open it and set HF_TOKEN.
        echo        File location: %CD%\.env
        notepad .env
        pause
    ) ELSE (
        echo [ERROR] Neither .env nor .env.example found. Please create a .env file.
        pause
        exit /b 1
    )
) ELSE (
    echo [OK] .env file found.
)

IF NOT EXIST "credentials.json" (
    echo.
    echo [WARN] credentials.json NOT found!
    echo        Download your Google OAuth credentials from Google Cloud Console:
    echo        https://console.cloud.google.com
    echo        Go to: APIs ^& Services -^> Credentials -^> Download OAuth client JSON
    echo        Rename the downloaded file to "credentials.json" and place it here:
    echo        %CD%\
    echo.
    pause
    exit /b 1
) ELSE (
    echo [OK] credentials.json found.
)
echo.

:: -------------------------------------------------------
:: Step 5: Gmail Push / ngrok reminder
::
:: Gmail Push Notifications need a public HTTPS URL.
:: See PUSH_SETUP.md for full ngrok install + GCP setup.
:: -------------------------------------------------------
echo [5/6] Gmail Push / ngrok reminder...
echo.
echo        To enable real-time Gmail Push Notifications:
echo          1. Set PUBSUB_TOPIC in .env  (see PUSH_SETUP.md for GCP setup)
echo          2. Run ngrok in a separate terminal:  ngrok http 8000
echo          3. Set WEBHOOK_BASE_URL to your ngrok HTTPS URL in .env
echo          (see PUSH_SETUP.md Step 2.5 for full ngrok install guide)
echo.
echo        Without push: startup catch-up fetch still processes missed emails.
echo.



:: -------------------------------------------------------
:: Step 6: Launch the FastAPI Server
:: -------------------------------------------------------
echo [6/6] Starting AI Email Agent server...
echo.
echo ============================================================
echo   Server   : http://localhost:8000
echo   Dashboard : http://localhost:8000/
echo   Webhook   : %WEBHOOK_BASE_URL%/webhook/gmail
echo   Press Ctrl+C to stop.
echo ============================================================
echo.

uvicorn app.main:app --host 0.0.0.0 --port 8000

:: If server exits cleanly
echo.
echo [INFO] Server stopped.
pause
