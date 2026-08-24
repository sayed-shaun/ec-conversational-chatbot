"""
Central logging setup shared by every service. Modules should call
`get_logger(__name__)` instead of configuring logging themselves, so all
services emit the same format at the same, env-controlled level.
"""

import logging
import os
import sys

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_configured = False


def configure_logging(level: str | None = None) -> None:
    """Install a single stderr handler on the root logger (idempotent).

    Level comes from the LOG_LEVEL env var (default INFO) unless passed
    explicitly. Logs go to stderr so stdout stays clean for the MCP stdio
    transport, where stdout is the protocol channel.
    """
    global _configured

    resolved = (level or os.getenv("LOG_LEVEL") or "INFO").upper()

    if _configured:
        logging.getLogger().setLevel(resolved)
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(resolved)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger, configuring logging on first use."""
    configure_logging()
    return logging.getLogger(name)
