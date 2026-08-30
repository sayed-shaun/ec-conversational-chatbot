"""
Entrypoint for both services in this repo.

    python main.py api      # FastAPI chatbot backend (default)
    python main.py mcp      # FastMCP search_faq server
    python main.py vector   # pgvector-backed FAQ search API

Two containers run from the same image-building context, so keeping both
entrypoints here means there is one obvious place to look for "how does this
start", rather than a CMD buried in each Dockerfile.

Everything configurable lives in src/core/config.py; nothing is hardcoded
here beyond the choice of which service to run.
"""

import argparse
import sys

from src.core.logger import get_logger

logger = get_logger(__name__)


def run_api() -> None:
    """Serve the chatbot backend with uvicorn."""
    import uvicorn

    from src.core.config import chatbot_settings as settings

    logger.info(
        "starting chatbot API on http://%s:%s", settings.api_host, settings.api_port
    )
    uvicorn.run(
        "src.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
    )


def run_mcp() -> None:
    """Serve the MCP search_faq server."""
    from src.mcp.server import main as mcp_main

    mcp_main()


def run_vector() -> None:
    """Serve the pgvector-backed FAQ search API."""
    import uvicorn

    from src.core.config import vector_settings as settings

    logger.info(
        "starting vector search API on http://%s:%s",
        settings.vector_api_host,
        settings.vector_api_port,
    )
    uvicorn.run(
        "src.vector.app:app",
        host=settings.vector_api_host,
        port=settings.vector_api_port,
    )


SERVICES = {"api": run_api, "mcp": run_mcp, "vector": run_vector}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "service",
        nargs="?",
        default="api",
        choices=sorted(SERVICES),
        help="which service to run (default: api)",
    )
    args = parser.parse_args(argv)

    SERVICES[args.service]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
