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
    application = FastAPI(title="EC Conversational Chatbot", version="1.0.0", lifespan=lifespan)

    origins = [o.strip() for o in settings.CORS_ALLOW_ORIGINS.split(",") if o.strip()]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
        # Without this the browser hides these from JS on a cross-origin
        # deploy (the UI on Vercel, this API elsewhere), and the streamed PCM
        # would be played at a guessed sample rate. Response headers are not
        # readable by default however permissive allow_headers is -- that
        # governs the REQUEST.
        expose_headers=["x-audio-sample-rate", "x-audio-channels", "x-audio-format"],
    )

    application.include_router(v1_router)

    @application.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @application.get("/", include_in_schema=False)
    async def index() -> RedirectResponse:
        """Convenience: bare localhost:8000 lands on the chat UI."""
        return RedirectResponse(url="/static/index.html")

    class NoCacheStaticFiles(StaticFiles):
        """StaticFiles that forbids caching of the UI.

        The UI is hand-edited HTML, CSS and JS served straight off a bind
        mount, so an edit is meant to be live on reload. Without this, browsers
        hold the previous copy and a fix looks like it did nothing -- which
        cost real debugging time chasing a bug that had already been fixed.
        It is a few tens of KB from a local server; there is nothing to gain
        by caching it.
        """

        def is_not_modified(self, *args, **kwargs) -> bool:
            return False

        async def get_response(self, path: str, scope):
            response = await super().get_response(path, scope)
            response.headers["Cache-Control"] = "no-store, must-revalidate"
            return response

    application.mount(
        "/static",
        NoCacheStaticFiles(directory=settings.STATIC_DIR, html=True),
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
