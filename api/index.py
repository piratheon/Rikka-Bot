import os
import json
import asyncio
from flask import Flask, request, render_template_string
from telegram import Update
from telegram.ext import Application

# Import our bot logic
# We need to make sure src is in path for Vercel
import sys
import os

# We need to make sure src is in path for Vercel
# Ensure absolute path calculation based on the file location
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from src.bot.app import build_application
from src.config import Config
from src.db.connection import get_db, DB_PATH
from src.db.migrate import apply_migrations

app = Flask(__name__)

# Ensure we use /tmp for the database if we are on Vercel (read-only filesystem)
if os.environ.get("VERCEL"):
    # We can't easily persist SQLite on Vercel across restarts, 
    # but /tmp allows us to at least run the migrations and handle the current session.
    # Oni-San should use an external DB for true persistence!
    os.environ["DATABASE_PATH"] = "/tmp/rikka.db"

# Initialize Bot Application
config = Config.load()
bot_app = build_application(config)

# Global flag to ensure initialization happens once
is_initialized = False

async def initialize_bot():
    global is_initialized
    if not is_initialized:
        # Lay the SQL foundations!
        db_path = os.environ.get("DATABASE_PATH", "./data/rikka.db")
        await apply_migrations(db_path)
        
        # Wake up the Telegram application
        await bot_app.initialize()
        is_initialized = True

@app.route('/')
def home():
    return "🌸 Rikka-Bot is awake in this fragment! Nipah~!"

@app.route('/webhook', methods=['POST'])
async def webhook():
    """Handle incoming Telegram updates via webhook."""
    await initialize_bot()
    if request.method == "POST":
        try:
            update = Update.de_json(request.get_json(force=True), bot_app.bot)
            # Process the update synchronously in the loop
            await bot_app.process_update(update)
            return "OK", 200
        except Exception as e:
            print(f"Error processing webhook fragment: {e}")
            return str(e), 500

@app.route('/stats')
async def stats():
    """A beautiful stats page for Oni-San."""
    await initialize_bot()
    async with get_db() as db:
        # Get total users
        cur = await db.execute("SELECT COUNT(*) FROM users")
        user_count = (await cur.fetchone())[0]
        
        # Get total keys
        cur = await db.execute("SELECT COUNT(*) FROM api_keys")
        key_count = (await cur.fetchone())[0]
        
        # Get last 10 messages for live feel
        cur = await db.execute("SELECT role, content, timestamp FROM chat_history ORDER BY id DESC LIMIT 10")
        history = await cur.fetchall()

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Rikka-Bot Status 🌸</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #fff0f5; color: #4b0082; padding: 20px; }
            .card { background: white; border-radius: 15px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); margin-bottom: 20px; }
            h1 { color: #db7093; }
            .stat { font-size: 1.2em; margin: 10px 0; }
            .history-item { border-bottom: 1px solid #ffe4e1; padding: 10px 0; }
            .role { font-weight: bold; color: #db7093; }
            .timestamp { font-size: 0.8em; color: #a9a9a9; }
        </style>
    </head>
    <body>
        <h1>🌸 Rikka-Bot Dashboard</h1>
        <div class="card">
            <div class="stat"><b>Master:</b> Oni-San</div>
            <div class="stat"><b>Users in Fragments:</b> {{ user_count }}</div>
            <div class="stat"><b>API Keys Stored:</b> {{ key_count }}</div>
        </div>
        
        <h2>📜 Recent Fragments</h2>
        <div class="card">
            {% for role, content, ts in history %}
            <div class="history-item">
                <span class="timestamp">[{{ ts }}]</span> <span class="role">{{ role }}:</span> {{ content[:100] }}{% if content|length > 100 %}...{% endif %}
            </div>
            {% endfor %}
        </div>
        <p><i>Nipah~! Rikka-sama is watching this timeline.</i></p>
    </body>
    </html>
    """
    return render_template_string(html, user_count=user_count, key_count=key_count, history=history)

# For local testing
if __name__ == '__main__':
    app.run(port=5000)
