# 🌸 Rikka-Bot

Rikka is an advanced, persona-driven Telegram AI agent built with Python. She features dynamic multi-agent orchestration, persistent memory, and a robust multi-provider key pool.

## ✨ Features

- **Dynamic Orchestration**: Rikka uses an internal meta-orchestrator to break down complex tasks into specialized agent plans.
- **Multi-Provider Support**: Seamless failover and rotation across **Gemini**, **Groq**, and **OpenRouter**.
- **Persistent Memory & Skills**: Rikka can autonomously save facts about the user and learn new "skills" stored in a SQLite database.
- **Metadata-Rich History**: Long-term context preservation using auto-summarization that keeps track of technical research findings.
- **LiveBubble™ UI**: Real-time status updates in Telegram using throttled message edits.
- **Powerful Tools**: Integrated Wikipedia (Official API) and `curl` for flexible web fetching.
- **Security First**: All user API keys are stored using AES-256-GCM encryption.

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.12+
- A Telegram Bot Token from [@BotFather](https://t.me/botfather)

### 2. Installation
```bash
git clone https://github.com/piratheon/Rikka-Bot.git
cd Rikka-Bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configuration
Copy `.env.template` to `.env` and fill in your tokens:
```env
TELEGRAM_BOT_TOKEN="your_token_here"
BOT_ENCRYPTION_KEY="your_64_char_hex_key"
```

### 4. Run
```bash
python -m src.db.migrate
python -m src.bot.app
```

## 🛠 Usage

- Send `/start` to wake Rikka up.
- Add your API keys by sending them in the chat: `openrouter:"sk-..."` or `groq:"gsk_..."`.
- Use `/addkey provider:"key"` for explicit adding.
- Chat naturally! Rikka will decide when to spawn agents for complex research.

## 🐳 Docker Deployment

```bash
docker-compose up -d
```

## 📜 License
MIT - see [LICENSE](LICENSE) file
