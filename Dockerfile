# syntax=docker/dockerfile:1
#
# selenium/standalone-chrome bundles version-matched Chrome + ChromeDriver.
# To update both at once: docker build --pull ... (pulls latest image)
# Tags: https://hub.docker.com/r/selenium/standalone-chrome/tags
FROM selenium/standalone-chrome:latest

USER root

# Install Python 3 + venv
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /root/mvgm-watcher

# Install dependencies into a venv (layer-cached separately from app code)
COPY requirements.txt .
RUN python3 -m venv .venv && \
    .venv/bin/pip install --quiet --upgrade pip && \
    .venv/bin/pip install --quiet -r requirements.txt

# Copy application code
COPY watcher.py .
COPY chromedriver_manager.py .

# /data is mounted from the host and contains:
#   .env              — all configuration (required)
#   last_listing.txt  — persisted state (written by the app)
#   watcher.log       — CRITICAL-only log (written by the app)
VOLUME ["/data"]

# Tell the app it's running inside Docker
ENV DOCKER=true

ENTRYPOINT [".venv/bin/python", "watcher.py"]
