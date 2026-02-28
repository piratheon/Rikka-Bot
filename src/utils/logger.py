import logging
import os
import structlog


def _ensure_log_dir(path: str):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


LOG_PATH = os.environ.get("RIKKA_LOG_PATH", "./rikka.log")
_ensure_log_dir(LOG_PATH)

# Configure stdlib logging to write to file
handler = logging.FileHandler(LOG_PATH)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
root = logging.getLogger()
root.setLevel(logging.INFO)
if not any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', None) == os.path.abspath(LOG_PATH) for h in root.handlers):
    root.addHandler(handler)

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)


def get_logger(name: str | None = None):
    return structlog.get_logger(name)


logger = get_logger("rikka")
