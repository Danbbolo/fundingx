FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Install the package itself
RUN pip install --no-cache-dir -e .

# Default entrypoint
ENTRYPOINT ["python", "-m", "fundingx"]
CMD ["--config", "config/default.yaml"]
