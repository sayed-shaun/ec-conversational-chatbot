/*
 * Base URL of the chatbot API. Empty means same-origin, which is what
 * this default supports when the page is served by the FastAPI app
 * itself (StaticFiles at /static) -- leave it as '' for that case.
 *
 * Set it to the backend URL only if the UI is served from elsewhere;
 * the backend must then allow that origin via CORS_ALLOW_ORIGINS.
 */
export const API_BASE = '';
