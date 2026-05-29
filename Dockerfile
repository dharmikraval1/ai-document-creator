FROM python:3.12-slim

# Install system dependencies (git is required to clone target repos)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files
COPY . .

# Expose default port
EXPOSE 8000

# Start the MCP server
CMD ["python", "mcp_server_impl.py"]
