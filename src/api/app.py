"""
ASGI application assembly.

Everything FastAPI-shaped lives in this package: this module builds the app
itself, and api/v1 declares the routes. `src/chatbot` below it is plain
domain logic with no web framework imported, so the dependency direction is
one-way -- api -> chatbot -> core.

- Includes the versioned API router (src/api/v1).
- Exposes a plain /health for container healthchecks.
- Mounts the static chat UI at /static, so the page lives at
  /static/index.html and its assets resolve as plain relative paths.
- Runs a background sweeper that clears finished (idle) conversations.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.api.v1 import router as v1_router
from src.chatbot.checkpointer import checkpointer
from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


async def sweep_expired_sessions() -> None:
    """Periodically clear conversations that have gone idle.

    A chat has no end signal over HTTP, so expiry is what "the chat ended"
    means in practice. Cancellation during shutdown is expected and is not an
    error.
    """
    interval = settings.session_sweep_minutes * 60
    while True:
        try:
            await asyncio.sleep(interval)
            await checkpointer.purge_expired()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session sweep failed; will retry next interval")


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Prepare the checkpointer, then run the sweeper for the app's lifetime.

    Ordering against llama-server is handled declaratively by depends_on /
    service_healthy in docker-compose.yml, not here.
    """
    checkpointer.init()
    await checkpointer.purge_expired()

    sweeper = None
    if settings.session_ttl_minutes > 0:
        sweeper = asyncio.create_task(sweep_expired_sessions())
        logger.info(
            "session expiry on: ttl=%dmin sweep=%dmin",
            settings.session_ttl_minutes,
            settings.session_sweep_minutes,
        )
    else:
        logger.info("session expiry off; transcripts kept until reset")

    try:
        yield
    finally:
        if sweeper is not None:
            sweeper.cancel()
            try:
                await sweeper
            except asyncio.CancelledError:
                pass


def create_app() -> FastAPI:
    application = FastAPI(title="EC FAQ Chatbot", version="1.0.0", lifespan=lifespan)

    application.include_router(v1_router)

    @application.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @application.get("/", include_in_schema=False)
    async def index() -> RedirectResponse:
        """Convenience: bare localhost:8000 lands on the chat UI."""
        return RedirectResponse(url="/static/index.html")

    application.mount(
        "/static",
        StaticFiles(directory=settings.static_dir, html=True),
        name="static",
    )

    logger.info(
        "chatbot app ready llama=%s mcp=%s static=%s",
        settings.llama_base_url,
        settings.mcp_server_url,
        settings.static_dir,
    )
    return application


app = create_app()
