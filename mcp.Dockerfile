FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Build context is the repo root, so src/core (shared config + logger) is
# available to this service too.
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[mcp]"

COPY main.py ./

ENV MCP_TRANSPORT=http
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=9000
ENV MCP_PATH=/mcp

EXPOSE 9000

CMD ["python", "main.py", "mcp"]
