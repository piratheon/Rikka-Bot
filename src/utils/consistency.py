from pathlib import Path

# A lightweight consistency check: ensure key Phase-1 files exist as described in README
EXPECTED = [
    "src/bot/app.py",
    "src/config.py",
    "config.json",
    ".env.template",
    "requirements.txt",
    "pyproject.toml",
]


def check_readme_vs_fs():
    missing = [p for p in EXPECTED if not Path(p).exists()]
    if missing:
        print("Readme consistency: missing files:\n- " + "\n- ".join(missing))
        return False
    print("Readme consistency: OK — expected Phase 1 files present.")
    return True


if __name__ == "__main__":
    check_readme_vs_fs()
