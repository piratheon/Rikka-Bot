#!/bin/bash

# Rikka-Bot Setup Script 🌸
echo "------------------------------------------------"
echo "   🌸 Rikka-Bot: Consulting the Fragments...   "
echo "------------------------------------------------"

# 1. Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Bakkaaa!! Python3 is not installed! Install it first, Oni-San!"
    exit 1
fi

# 2. Setup Virtual Environment
if [ ! -d ".venv" ]; then
    echo "Nipah~ Creating a cozy .venv for my fragments..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# 3. Install Requirements
echo "Mii~ Installing dependencies... please wait~"
pip install -q --upgrade pip
pip install -q -r requirements.txt

# 4. Handle .env Configuration
if [ ! -f ".env" ]; then
    echo "Oni-San, I need your Telegram Bot Token!"
    read -p "Paste it here (from @BotFather): " BOT_TOKEN
    echo "Who is my master? (Your Telegram User ID for admin commands):"
    read -p "ID: " OWNER_ID
    
    ENC_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    
    echo "TELEGRAM_BOT_TOKEN=\"$BOT_TOKEN\"" > .env
    echo "BOT_ENCRYPTION_KEY=\"$ENC_KEY\"" >> .env
    echo "OWNER_USER_ID=\"$OWNER_ID\"" >> .env
    echo "Nipah~ .env created with your master credentials!"
fi

# 5. Config Wizard (config.json)
if [ ! -f "config.json" ]; then
    echo "Do you want to configure my internal soul now? (y/n)"
    read -p "> " DO_CONFIG
    if [ "$DO_CONFIG" == "y" ]; then
        echo "Which model should I use by default? (e.g., gemini-2.0-flash)"
        read -p "Model: " DEF_MODEL
        echo "{\"default_model\": \"$DEF_MODEL\"}" > config.json
        echo "Soul fragments aligned!"
    else
        echo "Using default soul settings for now~"
    fi
fi

# 6. Run Migrations
echo "Pachi-pachi! Aligning the database fragments..."
python3 -m src.db.migrate

# 7. Start the Bot
echo "Rikka-sama is waking up! Do not blink, Oni-San! ✨"
python3 -m src.bot.app
