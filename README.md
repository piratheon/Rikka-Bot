<div align="center">

<br/>

```
██████╗ ██╗██╗  ██╗ █████╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗
██╔══██╗██║██║ ██╔╝██╔══██╗     ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
██████╔╝██║█████╔╝ ███████║     ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   
██╔══██╗██║██╔═██╗ ██╔══██║     ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   
██║  ██║██║██║  ██╗██║  ██║     ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   
╚═╝  ╚═╝╚═╝╚═╝  ╚═╝╚═╝  ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   
```

<h3>Self-hosted agentic AI on your own hardware — Telegram-native, privacy-first.</h3>

<br/>

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot_API-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](docker-compose.yml)
[![SQLite](https://img.shields.io/badge/Storage-SQLite_%2B_Qdrant-003B57?style=flat-square&logo=sqlite&logoColor=white)](#architecture)
[![Security](https://img.shields.io/badge/Keys-AES--256--GCM-dc2626?style=flat-square&logo=keepassxc&logoColor=white)](#security)

[![Gemini](https://img.shields.io/badge/Gemini-2.0_Flash-4285F4?style=flat-square&logo=google&logoColor=white)](#providers)
[![Groq](https://img.shields.io/badge/Groq-llama3.3_70b-f97316?style=flat-square)](#providers)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-200%2B_models-7c3aed?style=flat-square)](#providers)
[![Ollama](https://img.shields.io/badge/Ollama-local%2C_free-111827?style=flat-square)](#ollama--g4f)
[![G4F](https://img.shields.io/badge/G4F-no_key_needed-16a34a?style=flat-square)](#ollama--g4f)

<br/>

</div>

---

> **rika-agent** is the evolution of [Rikka-Bot](https://github.com/piratheon/rika-agent/releases/tag/v2.0.0). Same soul, continuously refined architecture. v2.1 ships JSON function calling, background system monitoring, a three-level code sandbox, vision input, file delivery, token-efficient context, and Ollama/G4F support — running entirely on your own server, with your data staying yours.

---

## What it actually does

Most "AI assistants" are wrappers that relay your messages to an API. rika-agent is different: it runs as a persistent process on your machine with real access to your shell, file system, and network. The agent decides when to use tools, chains multiple calls together, monitors your server in the background, and delivers results — including actual files — back to you in Telegram.

```
you → "analyze the last 200 nginx errors, find patterns, write a report"

rika → [run_shell_command: tail -200 /var/log/nginx/error.log]
        [web_search: common nginx 502 causes 2025]
        [run_python: parse log entries, cluster by error type]
        [writes report.md to workspace]
        [sends report.md as Telegram file attachment]
        "Found 3 patterns. Most common: upstream timeout (67%). Report attached."
```

No copy-paste. No switching tabs. It just does it.

---

## Features

<table>
<tr>
<td width="50%">

**Core agent**
- JSON function calling via native provider APIs — no regex parsing
- Multi-turn ReAct loop (up to 8 tool calls per request)
- Text-protocol fallback when function calling unavailable
- 3-tier complexity classifier (skips LLM call for greetings)
- Per-user concurrency limit (max 2 simultaneous tasks)

</td>
<td width="50%">

**Providers**
- Gemini, Groq, OpenRouter — key rotation with LRU selection
- Ollama — local models, zero cost, zero data egress
- G4F — free endpoints (GPT-4o, Claude, Llama), no key needed
- Blacklist + quota-reset scheduling per provider
- Per-provider locks prevent thundering-herd races

</td>
</tr>
<tr>
<td>

**Background monitoring** *(zero AI tokens at rest)*
- `SystemWatcher` — CPU load, memory %, disk % via `/proc`
- `ProcessWatcher` — process presence detection
- `URLWatcher` — HTTP health check, state-change alerts
- `PortWatcher` — TCP port availability
- `LogPatternWatcher` — regex tail on any log file
- `CronWatcher` — scheduled AI tasks on any interval
- `ScriptWatcher` — execute agent-authored monitoring scripts
- AI-driven setup: `/autowatch "guard my server"` → auto-creates watchers
- One LLM call per anomaly → Telegram alert
- All configs survive restarts

</td>
<td>

**Tools**
- `web_search` — DuckDuckGo, no API key
- `wikipedia_search` — MediaWiki REST API
- `curl` — fetch any URL, stripped to readable text
- `run_shell_command` — host shell, cwd = workspace
- `run_python` — configurable isolation sandbox
- `send_file` — deliver workspace files to Telegram
- `list_workspace` — browse the agent's sandbox
- `save_memory` / `get_memories` / `save_skill`
- `delegate_task` — spawn a research sub-agent

</td>
</tr>
<tr>
<td>

**Security**
- AES-256-GCM encryption for all stored API keys
- 22-rule shell command firewall — pure Python, zero AI tokens
  - **CRITICAL**: `rm -rf /`, fork bombs, disk wipes → blocked unconditionally
  - **HIGH**: kill init, flush iptables → blocked in standard/strict
  - **MEDIUM**: `curl | bash`, `sudo su` → `CONFIRM:` prefix to override
- File delivery path-traversal protection
- Access control via `allowed_user_ids`

</td>
<td>

**Memory & context**
- Qdrant vector store — semantic recall across sessions
- Per-user key-value memory (facts, preferences, skills)
- Token-efficient injection: pinned (max 5) + relevant (top 4) only
- Memory pinning: `/pinmemory` / `/unpinmemory` commands
- Auto-summarization when context window fills
- Runtime context injected per-message (time, host, OS, user)
- Config singleton with 30s TTL — no disk read per message

</td>
</tr>
<tr>
<td>

**Vision**
- Send any photo → bot downloads, base64-encodes, sends to provider
- Gemini (native multimodal) and OpenRouter (vision models)
- Caption becomes the query; no caption = full description

</td>
<td>

**UX**
- LiveBubble™ — throttled Telegram message edits with Braille spinner
- `AGENT_NAME=lain` in `.env` — name your agent anything you want
- `/reload` hot-reloads config + registry without restart
- Command audit log via `/cmdhistory`
- Workspace management via `/files`, `/cleanworkspace`

</td>
</tr>
</table>

---

## Quick start

**Requirements:** Python 3.12+, Telegram bot token from [@BotFather](https://t.me/BotFather)

```bash
git clone https://github.com/piratheon/rika-agent
cd rika-agent
bash scripts/bot_setup.sh
```

The setup wizard handles everything: bot token, agent name, provider keys, sandbox level detection, optional Ollama/G4F configuration, and database migration. When done:

```bash
bash scripts/start.sh
```

**Docker:**
```bash
cp .env.template .env   # fill TELEGRAM_BOT_TOKEN and BOT_ENCRYPTION_KEY
docker compose up -d
docker compose logs -f
```

---

## Configuration

### `.env` — secrets

```env
# Required
TELEGRAM_BOT_TOKEN=
BOT_ENCRYPTION_KEY=   # generate: python3 -c "import secrets; print(secrets.token_hex(32))"

# Optional
DATABASE_PATH=./data/rk.db
OWNER_USER_ID=        # your Telegram ID — enables /broadcast and /reload
AGENT_NAME=lain       # display name in all messages (lain, rei, Rika, aria...)

# Pre-loaded provider keys (can also be added via /addkey in Telegram)
GEMINI_API_KEY=
GROQ_API_KEY=
OPENROUTER_API_KEY=
```

> `AGENT_NAME` is purely cosmetic — the project name stays `rika-agent`. Set it to whatever you want your agent to call itself.

### `config.json` — behavior

```json
{
  "bot_name": "rika-agent",
  "default_model": "gemini-2.0-flash",
  "default_provider_priority": ["groq", "openrouter", "gemini"],

  "sandbox_level": 1,
  "enable_command_security": true,
  "command_security_level": "standard",

  "workspace_path": "~/.Rika-Workspace",

  "ollama_enabled": false,
  "ollama_base_url": "http://localhost:11434",
  "ollama_default_model": "llama3.2",
  "g4f_enabled": false,
  "g4f_model": "MiniMaxAI/MiniMax-M2.5",

  "max_context_messages": 40,
  "max_concurrent_orchestrations_per_user": 2,
  "max_background_agents_per_user": 10,
  "tool_timeout_seconds": 10,

  "groq_model": "llama-3.3-70b-versatile",
  "openrouter_model": "google/gemini-2.0-flash-001",
  "gemini_model": "gemini-2.0-flash",
  "ollama_model": "llama3.2"
}
```

### `soul.md` — personality

The agent's tone, instructions, and character. Loaded at startup. Gitignored by default — edit freely without touching the codebase. Changes take effect on `/reload` or within 30 seconds.

```bash
cp soul.md.template soul.md
$EDITOR soul.md
```

---

## Providers

### Keyed

| Provider | Free tier | Notes |
|---|---|---|
| **Gemini** | Yes (generous) | Best multimodal, 1M context, native vision |
| **Groq** | Yes | Fastest inference — llama3.3-70b, mixtral |
| **OpenRouter** | Pay-per-token | 200+ models including GPT-4o, Claude 3.5 |

Add via `/addkey` in Telegram or paste `provider:"key"` pairs directly in chat. Multiple keys per provider — the pool rotates automatically.

### Ollama & G4F

<details>
<summary><b>Ollama — local inference, zero cost, data never leaves your machine</b></summary>

```bash
# Install: https://ollama.com
ollama pull llama3.2
ollama serve
```

```json
{
  "ollama_enabled": true,
  "ollama_base_url": "http://localhost:11434",
  "ollama_default_model": "llama3.2",
  "default_provider_priority": ["ollama", "groq", "gemini"]
}
```

Auto-discovers models via `/api/tags`. Falls back to first available if requested model not found.

</details>

<details>
<summary><b>G4F — free access to GPT-4o, Claude, Gemini Pro</b></summary>

> **Warning:** G4F relies on reverse-engineered endpoints. It can break at any time. Use as last-resort fallback only.

```bash
pip install g4f
```

```json
{ "g4f_enabled": true }
```

</details>

---

## Code sandbox

Set `sandbox_level` in `config.json`:

| Level | Name | What the agent can do | Requirements |
|---|---|---|---|
| `0` | RestrictedPython | Arithmetic and logic only. No file I/O, no imports. | None |
| `1` | Process + ulimit | Full Python, installed packages, write to workspace. CPU/RAM capped. | Linux / macOS |
| `2` | Docker | No network, memory-capped, ephemeral container. Maximum isolation. | Docker running |

The setup wizard detects your environment and recommends the highest available level.

> *"With great power comes great responsibility."* — Linus Torvalds

Level 2 is strongly recommended for any multi-user or public deployment.

---

## Background monitoring

```
/watch system  (every 120s)
      │
      └─ SystemWatcher.check()     ← pure Python, reads /proc, zero API cost
              │  load > 4.0
              ▼
          WakeSignal → queue
              │
              └─ WakeProcessor
                      └─ 1 LLM call → Telegram alert

"[CRIT] sys_3f7a — Load hit 6.2, memory at 91%.
 Likely runaway process. Check: ps aux --sort=-%mem | head -10"
```

```
/watch system                               CPU / memory / disk
/watch system cpu:90 mem:95                 custom thresholds
/watch process postgres                     process presence
/watch url https://mysite.com               HTTP health check
/watch port 5432                            TCP availability
/watch log /var/log/app.log "ERROR|FATAL"   regex in log file
/watch cron 30m summarize disk and warn if above 80%
/autowatch "guard my server"                AI-driven watcher setup

/watchers          list active agents
/stopwatch <id>    stop one
/wakelog           recent alerts
```

---

## Command reference

| Command | Description |
|---|---|
| `/start` | Initialize the bot |
| `/help` | Full command list |
| `/addkey provider:"key"` | Add an API key |
| `/status` | Keys, model, active agents |
| `/providers` | Provider connectivity + Ollama model list |
| `/reload` | Hot-reload config (owner only) |
| `/memory` | List stored memories and skills |
| `/pinmemory <key>` | Pin a memory for always-injection (max 5) |
| `/unpinmemory <key>` | Remove from always-injected list |
| `/deletememory <key>` | Delete a memory entry |
| `/autowatch <goal>` | AI-driven watcher setup (natural language) |
| `/watch <type> ...` | Register background monitor |
| `/watchers` | List active monitors |
| `/stopwatch <id>` | Stop a monitor |
| `/wakelog` | Recent wake events |
| `/files` | Workspace tree listing |
| `/cleanworkspace` | Wipe workspace contents |
| `/cmdhistory` | Command audit log |
| `/delete_me` | Delete all your data |

---

## Architecture

```
Telegram (app.py)
├── Photo ──────────────► vision provider → reply
├── Simple ─────────────► ProviderPool.request_with_key() → reply
└── Complex ────────────► orchestration loop
                               ReAct (max 8 turns)
                               request_with_tools() → StructuredResponse
                               execute_tool(name, {args}) → result
                               → optional file delivery

BackgroundAgentManager (singleton)
├── Watcher asyncio.Tasks  (pure Python, zero LLM tokens)
└── WakeProcessor task     (1 LLM call per fired signal)

ProviderPool (singleton)
├── Keyed: Gemini · Groq · OpenRouter
└── Keyless: Ollama · G4F

Storage
├── SQLite  users · api_keys [AES-256-GCM] · chat_history
│           rika_memory · background_agents · wake_events · command_audit
└── Qdrant  collection: collective_unconscious
```

---

## Project layout

```
rika-agent/
├── src/
│   ├── agents/
│   │   ├── background/         zero-token watchers + WakeProcessor
│   │   ├── agent_factory.py    ConcreteAgent — function-calling ReAct loop
│   │   ├── agent_bus.py        parallel + dependency-ordered runner
│   │   └── agent_models.py     AgentSpec, WakeSignal, BackgroundAgentConfig
│   ├── bot/app.py              all handlers + orchestration loop
│   ├── db/                     migrations, chat store, vector store, background store
│   ├── providers/
│   │   ├── base_provider.py    StructuredResponse, ToolCall, abstract base
│   │   ├── gemini_provider.py  function calling + vision
│   │   ├── groq_provider.py    function calling
│   │   ├── openrouter_provider.py
│   │   ├── ollama_provider.py  local LLM
│   │   ├── g4f_provider.py     free endpoints
│   │   └── provider_pool.py    singleton, key rotation, failover
│   └── tools/
│       ├── schemas.py          JSON Schema for all 11 tools
│       ├── sandbox.py          3-level code isolation
│       ├── command_security.py 22-rule shell firewall
│       ├── shell_tool.py       async shell + audit log
│       └── web_search_tool.py  DuckDuckGo scraper
├── scripts/
│   ├── bot_setup.sh            interactive wizard
│   └── start.sh                pre-flight + launch
├── config.json                 runtime config (no secrets)
├── soul.md.template            agent personality starting point
├── .env.template               all env vars documented
├── docker-compose.yml
├── ToDo.md                     GTK4 UI · WebUI · roadmap
└── README.md
```

---

## v2.0 → v2.1 changelog

| | rika-agent v2.0 | rika-agent v2.1 |
|---|---|---|
| Background monitoring | 6 watcher types | 7 watcher types — adds `ScriptWatcher` |
| Watcher setup | Manual `/watch` commands only | `/autowatch` — AI-driven natural language setup |
| Memory injection | Full history dump | Pinned (max 5) + relevant (top 4) only — token-efficient |
| Memory pinning | Not available | `/pinmemory` / `/unpinmemory` commands |
| Tool timeout | No per-tool limit | `tool_timeout_seconds` in `config.json` |
| Per-model config | Single `default_model` key | Per-provider model keys (`groq_model`, `openrouter_model`, etc.) |
| G4F model | Default only | `g4f_model` configurable in `config.json` |

---

## Security

<details>
<summary>API key encryption</summary>

AES-256-GCM. Generate your key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```
The key never touches the database. If `.env` is gone, stored keys are unrecoverable.

</details>

<details>
<summary>Shell command firewall</summary>

22 rules evaluated before every `run_shell_command` call. Zero AI tokens, zero latency.

Three security levels in `config.json`:
- `"standard"` — CRITICAL + HIGH blocked, MEDIUM needs `CONFIRM:` prefix
- `"strict"` — also blocks `curl | bash`, `sudo su`, service-disabling
- `"permissive"` — CRITICAL only (for trusted personal use)

</details>

<details>
<summary>File delivery</summary>

`send_file` resolves symlinks and rejects any path outside `~/.Rika-Workspace`. `../` traversal attempts are blocked and logged.

</details>

---

## Contributing

Issues and PRs welcome. For security issues, open a private issue rather than disclosing publicly.

---

<div align="center">

Built in Zagora, Morocco, by [piratheon](https://github.com/piratheon) ; inspired by the works of [Lain](https://lainchan.org/), [Rei](https://www.reddit.com/r/ReiAyanami/), and countless cyberpunk dreamers xD!

</div>
