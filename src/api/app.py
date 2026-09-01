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
- Allows cross-origin requests from CORS_ALLOW_ORIGINS, for a UI hosted
  separately from this API (e.g. on Vercel).
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
    interval = settings.SESSION_SWEEP_MINUTES * 60
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
    if settings.SESSION_TTL_MINUTES > 0:
        sweeper = asyncio.create_task(sweep_expired_sessions())
        logger.info(
            "session expiry on: ttl=%dmin sweep=%dmin",
            settings.SESSION_TTL_MINUTES,
            settings.SESSION_SWEEP_MINUTES,
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

    origins = [o.strip() for o in settings.CORS_ALLOW_ORIGINS.split(",") if o.strip()]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
        StaticFiles(directory=settings.STATIC_DIR, html=True),
        name="static",
    )

    logger.info(
        "chatbot app ready llama=%s mcp=%s static=%s",
        settings.LLAMA_BASE_URL,
        settings.MCP_SERVER_URL,
        settings.STATIC_DIR,
    )
    return application


app = create_app()
