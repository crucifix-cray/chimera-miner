FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    xvfb \
    chromium \
    chromium-driver \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy application files
COPY . .

# Set environment
ENV DISPLAY=:99
ENV PYTHONUNBUFFERED=1

# Start command
CMD ["python3", "run_miner.py"]
