FROM python:3.12-slim

# git is required to clone target repos
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the package itself
COPY . .
RUN pip install --no-cache-dir --no-deps .

# Expose default port (the platform's PORT env var takes precedence at runtime)
EXPOSE 8000

# Serves Streamable HTTP at /mcp (+ legacy SSE at /sse) when PORT is set
CMD ["python", "-m", "ai_doc_creator.server"]
