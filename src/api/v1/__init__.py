"""Version 1 of the public HTTP API, served under /api/v1."""

from src.api.v1.routes import router

__all__ = ["router"]
