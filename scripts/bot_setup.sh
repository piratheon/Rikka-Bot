#!/usr/bin/env bash
# rk-agent setup wizard v3
set -euo pipefail

R="\033[0;31m" G="\033[0;32m" Y="\033[0;33m" B="\033[0;34m"
C="\033[0;36m" W="\033[1;37m" D="\033[2m" NC="\033[0m"
OK="${G}✓${NC}" ERR="${R}✗${NC}" WARN="${Y}!${NC}" NFO="${C}→${NC}"

say()  { echo -e "  $*"; }
ok()   { echo -e "  ${OK} $*"; }
err()  { echo -e "  ${ERR} ${R}$*${NC}"; }
warn() { echo -e "  ${WARN} ${Y}$*${NC}"; }
info() { echo -e "  ${NFO} ${D}$*${NC}"; }
hr()   { echo -e "  ${D}──────────────────────────────────────${NC}"; }
ask()  { echo -en "  ${B}?${NC} $1 "; }

header() { echo ""; echo -e "  ${W}$*${NC}"; hr; }

check_cmd() { command -v "$1" &>/dev/null; }
require_cmd() {
    if ! check_cmd "$1"; then
        err "$1 is required but not installed."
        exit 1
    fi
}

clear
echo ""
echo -e "  ${C}╔══════════════════════════════════════════╗${NC}"
echo -e "  ${C}║           rk-agent  v3  setup            ║${NC}"
echo -e "  ${C}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Requirements ─────────────────────────────────────────────────────────────
header "Checking requirements"
require_cmd python3

PY=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
MAJ=$(echo "$PY" | cut -d. -f1); MIN=$(echo "$PY" | cut -d. -f2)
[[ "$MAJ" -lt 3 || ( "$MAJ" -eq 3 && "$MIN" -lt 12 ) ]] && { err "Python 3.12+ required. Got $PY"; exit 1; }
ok "Python $PY"
check_cmd git && ok "git" || warn "git not found (optional)"
DOCKER_OK=false; check_cmd docker && docker info &>/dev/null 2>&1 && DOCKER_OK=true && ok "Docker (available for sandbox level 2)" || info "Docker not found or not running"

# ── Virtualenv ────────────────────────────────────────────────────────────────
header "Python environment"
if [ ! -d ".venv" ]; then
    info "Creating .venv..."
    python3 -m venv .venv; ok "Created .venv"
else 
 echo ".venv already exists"; fi
source .venv/bin/activate
info "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "Dependencies installed"

# ── .env ─────────────────────────────────────────────────────────────────────
header "Configuration — .env"
SKIP_ENV=0
if [ -f ".env" ]; then
    warn ".env already exists."
    ask "Reconfigure it? [y/N]"; read -r RE; [[ "$RE" =~ ^[Yy]$ ]] || SKIP_ENV=1
fi

if [ "$SKIP_ENV" -eq 0 ]; then
    echo ""
    say "Get a bot token from ${C}@BotFather${NC} on Telegram:"
    say "  /newbot → follow prompts → copy the token"
    echo ""
    ask "Telegram bot token:"; read -r BOT_TOKEN
    [[ -z "$BOT_TOKEN" ]] && { err "Token required."; exit 1; }

    echo ""
    say "Your Telegram user ID (message ${C}@userinfobot${NC} to find it):"
    ask "Your Telegram ID (Enter to skip):"; read -r OWNER_ID

    echo ""
    say "Give your agent a name! (optional, press Enter for default)"
    say "  Examples: lain, rei, Rika, aria, cipher"
    ask "Agent name:"; read -r AGENT_NAME
    AGENT_NAME="${AGENT_NAME:-}"

    ENC_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')

    {
        echo "TELEGRAM_BOT_TOKEN=\"$BOT_TOKEN\""
        echo "BOT_ENCRYPTION_KEY=\"$ENC_KEY\""
        echo "DATABASE_PATH=./data/rk.db"
        [ -n "$OWNER_ID" ] && echo "OWNER_USER_ID=\"$OWNER_ID\""
        [ -n "$AGENT_NAME" ] && echo "AGENT_NAME=\"$AGENT_NAME\""
        echo "LOG_LEVEL=info"
    } > .env
    ok ".env created (encryption key auto-generated)"

    echo ""
    header "Provider API keys"
    say "Press Enter to skip any. You can add them later with /addkey."
    echo ""
    ask "Gemini (aistudio.google.com):";   read -r GK
    ask "Groq (console.groq.com):";        read -r GROQK
    ask "OpenRouter (openrouter.ai):";     read -r ORK

    [ -n "$GK" ]    && echo "GEMINI_API_KEY=\"$GK\""        >> .env
    [ -n "$GROQK" ] && echo "GROQ_API_KEY=\"$GROQK\""       >> .env
    [ -n "$ORK" ]   && echo "OPENROUTER_API_KEY=\"$ORK\""   >> .env
    ok "Provider keys saved"
fi

# ── soul.md ───────────────────────────────────────────────────────────────────
header "Agent identity — soul.md"
if [ ! -f "soul.md" ]; then
    cp soul.md.template soul.md; ok "soul.md created from template"
    say "Edit ${C}soul.md${NC} to customize the agent's personality."
else
 echo "soul.md exists"; fi

# ── Sandbox setup ─────────────────────────────────────────────────────────────
header "Code execution sandbox"
say "The sandbox controls how safely the agent runs Python code."
say ""
say "  ${W}Level 0${NC} — RestrictedPython   — in-process, no file/network access"
say "  ${W}Level 1${NC} — Process + ulimit   — real Python, resource-limited   ${G}(recommended)${NC}"
say "  ${W}Level 2${NC} — Docker             — full isolation, max security     ${C}(best if Docker available)${NC}"
echo ""

BEST_LEVEL=0
if $DOCKER_OK; then
    BEST_LEVEL=2
    say "  Docker is available — ${C}Level 2 recommended${NC}"
elif python3 -c "import platform; exit(0 if platform.system() in ('Linux','Darwin') else 1)" 2>/dev/null; then
    BEST_LEVEL=1
    say "  Linux/macOS detected — ${C}Level 1 recommended${NC}"
else
    say "  Windows detected — ${C}Level 0 recommended${NC}"
fi
echo ""
ask "Sandbox level [0/1/2, Enter for $BEST_LEVEL]:"; read -r SB_INPUT
SB_LEVEL="${SB_INPUT:-$BEST_LEVEL}"
[[ "$SB_LEVEL" =~ ^[012]$ ]] || SB_LEVEL="$BEST_LEVEL"

# Write sandbox_level to config.json
if [ -f "config.json" ]; then
    python3 -c "
import json; c=json.load(open('config.json'))
c['sandbox_level']=$SB_LEVEL
json.dump(c,open('config.json','w'),indent=2)
print('sandbox_level set to $SB_LEVEL')
"
else
    echo "{\"sandbox_level\": $SB_LEVEL}" > config.json
    ok "config.json created with sandbox_level=$SB_LEVEL"
fi
ok "Sandbox level $SB_LEVEL configured"

if [ "$SB_LEVEL" -eq 2 ] && $DOCKER_OK; then
    info "Pre-pulling Docker image python:3.12-slim..."
    docker pull python:3.12-slim -q && ok "Docker image ready" || warn "Docker pull failed — will pull on first run"
fi

# ── Ollama (optional) ─────────────────────────────────────────────────────────
header "Local LLM — Ollama (optional)"
say "Ollama lets the agent use local models (llama3, mistral, etc.) for free."
say "Install from ${C}https://ollama.com${NC} then run: ollama pull llama3.2"
echo ""
ask "Enable Ollama integration? [y/N]:"; read -r OL_EN
if [[ "$OL_EN" =~ ^[Yy]$ ]]; then
    ask "Ollama URL [http://localhost:11434]:"; read -r OL_URL
    OL_URL="${OL_URL:-http://localhost:11434}"
    ask "Default model [llama3.2]:"; read -r OL_MODEL
    OL_MODEL="${OL_MODEL:-llama3.2}"
    python3 -c "
import json; c=json.load(open('config.json'))
c['ollama_enabled']=True; c['ollama_base_url']='$OL_URL'; c['ollama_default_model']='$OL_MODEL'
json.dump(c,open('config.json','w'),indent=2)
"
    ok "Ollama enabled: $OL_URL ($OL_MODEL)"
else
 info "Ollama skipped"; fi

# ── G4F (optional) ───────────────────────────────────────────────────────────
header "Free providers — G4F (optional)"
say "G4F provides free access to GPT-4, Claude, etc. via reverse-engineered APIs."
warn "G4F is unstable and may break without notice. Use as a last-resort fallback."
echo ""
ask "Install and enable G4F? [y/N]:"; read -r G4F_EN
if [[ "$G4F_EN" =~ ^[Yy]$ ]]; then
    info "Installing g4f..."
    pip install --quiet g4f
    python3 -c "import json; c=json.load(open('config.json')); c['g4f_enabled']=True; json.dump(c,open('config.json','w'),indent=2)"
    ok "G4F installed and enabled"
else
 info "G4F skipped"; fi

# ── Database ──────────────────────────────────────────────────────────────────
header "Database"
mkdir -p data
info "Running migrations..."
python3 -m src.db.migrate && ok "Database ready"

# ── Workspace ─────────────────────────────────────────────────────────────────
mkdir -p "$HOME/.Rika-Workspace"
ok "Agent workspace: $HOME/.Rika-Workspace"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${G}╔══════════════════════════════════════════╗${NC}"
echo -e "  ${G}║            Setup complete!               ║${NC}"
echo -e "  ${G}╚══════════════════════════════════════════╝${NC}"
echo ""
say "Start the bot:"
say "  ${C}bash scripts/start.sh${NC}"
echo ""
say "With Docker:"
say "  ${C}docker compose up -d${NC}"
echo ""
