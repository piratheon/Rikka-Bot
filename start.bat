@echo off
setlocal enabledelayedexpansion

:: Rikka-Bot Setup Script for Windows 🌸
echo ------------------------------------------------
echo    🌸 Rikka-Bot: Consulting the Fragments...   
echo ------------------------------------------------

:: 1. Check for Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Bakkaaa!! Python is not installed or not in PATH! Install it first, Oni-San!
    pause
    exit /b 1
)

:: 2. Setup Virtual Environment
if not exist ".venv" (
    echo Nipah~ Creating a cozy .venv for my fragments...
    python -m venv .venv
)

call .venv\Scripts\activate

:: 3. Install Requirements
echo Mii~ Installing dependencies... please wait~
pip install -q --upgrade pip
pip install -q -r requirements.txt

:: 4. Handle .env Configuration
if not exist ".env" (
    echo Oni-San, I need your Telegram Bot Token!
    set /p BOT_TOKEN="Paste it here (from @BotFather): "
    echo Who is my master? (Your Telegram User ID for admin commands):
    set /p OWNER_ID="ID: "
    
    for /f "tokens=*" %%i in ('python -c "import secrets; print(secrets.token_hex(32))"') do set ENC_KEY=%%i
    
    echo TELEGRAM_BOT_TOKEN="!BOT_TOKEN!" > .env
    echo BOT_ENCRYPTION_KEY="!ENC_KEY!" >> .env
    echo OWNER_USER_ID="!OWNER_ID!" >> .env
    echo Nipah~ .env created with your master credentials!
)

:: 5. Config Wizard (config.json)
if not exist "config.json" (
    echo Do you want to configure my internal soul now? (y/n)
    set /p DO_CONFIG="> "
    if "!DO_CONFIG!"=="y" (
        echo Which model should I use by default? (e.g., gemini-2.0-flash)
        set /p DEF_MODEL="Model: "
        echo {"default_model": "!DEF_MODEL!"} > config.json
        echo Soul fragments aligned!
    else (
        echo Using default soul settings for now~
    )
)

:: 6. Run Migrations
echo Pachi-pachi! Aligning the database fragments...
python -m src.db.migrate

:: 7. Start the Bot
echo Rikka-sama is waking up^! Do not blink, Oni-San^! ✨
python -m src.bot.app
pause
