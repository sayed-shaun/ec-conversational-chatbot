FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Build context is the repo root, so src/core (shared config + logger) is
# available to this service too.
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[vector]"

COPY main.py ./

ENV VECTOR_API_HOST=0.0.0.0
ENV VECTOR_API_PORT=8001

EXPOSE 8001

CMD ["python", "main.py", "vector"]
