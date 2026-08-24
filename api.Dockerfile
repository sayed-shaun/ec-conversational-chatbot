FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Built with the repo root as context. One container holds both the FastAPI
# service and the OpenAI SDK client that talks to llama-server.
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[chatbot]"

COPY static/ ./static/
COPY main.py ./

EXPOSE 8000

# Host and port come from src/core/config.py (API_HOST / API_PORT).
CMD ["python", "main.py", "api"]
