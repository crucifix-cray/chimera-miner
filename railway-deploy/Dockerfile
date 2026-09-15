FROM ubuntu:24.04

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    firefox \
    xvfb \
    curl \
    git \
    rclone \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright and Firefox
RUN pip3 install --break-system-packages playwright && \
    playwright install firefox && \
    playwright install-deps firefox

# Create working directory
WORKDIR /app

# Copy miner files
COPY script3_launch_miner.py .
COPY miner_injector.py .
COPY mega_db.py .
COPY railway-deploy/rclone.conf /root/.config/rclone/rclone.conf
COPY railway-deploy/sessions /app/sessions
COPY railway-deploy/start.sh .

# Make start script executable
RUN chmod +x start.sh

# Expose port for health check (optional)
EXPOSE 8080

# Keep container running with tail -f
CMD ["bash", "-c", "tail -f /dev/null"]
