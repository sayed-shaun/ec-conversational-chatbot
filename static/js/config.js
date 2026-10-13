/*
 * Base URL of the chatbot API. Empty means same-origin, which is what
 * this default supports when the page is served by the FastAPI app
 * itself (StaticFiles at /static) -- leave it as '' for that case.
 *
 * When the UI is deployed separately (e.g. to Vercel), vercel.json's
 * buildCommand patches this line at build time from the NGROK_URL
 * environment variable set in the Vercel project, so the public tunnel
 * URL never has to be hardcoded or committed. The backend must also
 * allow the Vercel origin via CORS_ALLOW_ORIGINS and be reachable over
 * HTTPS, since an HTTPS page cannot call a plain HTTP API.
 */
export const API_BASE = '';
