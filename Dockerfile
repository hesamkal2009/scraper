# syntax=docker/dockerfile:1
#
# selenium/standalone-chrome bundles version-matched Chrome + ChromeDriver.
# To update both at once: docker build --pull ... (pulls latest image)
# Tags: https://hub.docker.com/r/selenium/standalone-chrome/tags
# Base image includes Selenium, Chrome, and ChromeDriver for browser automation
FROM selenium/standalone-chrome:latest

USER root

# Install Python 3 and create a virtual environment for the app
RUN echo "[Docker build] Installing Python and runtime prerequisites..."
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container for application files
WORKDIR /root/HouseCheckerV2
RUN echo "[Docker build] Working directory set to /root/HouseCheckerV2"

# Install Python dependencies into a virtual environment
COPY requirements.txt .
RUN python3 -m venv .venv && \
    .venv/bin/pip install --quiet --upgrade pip && \
    .venv/bin/pip install --quiet -r requirements.txt

# Copy the application source files into the image
COPY watcher.py .
COPY chromedriver_manager.py .

# Mount /data from the host so secrets and state persist outside the container
#   .env              — all configuration (required)
#   last_listing.txt  — persisted state (written by the app)
#   watcher.log       — CRITICAL-only log (written by the app)
VOLUME ["/data"]

# Set runtime environment to Docker mode and execute the watcher entrypoint
ENV DOCKER=true

ENTRYPOINT [".venv/bin/python", "watcher.py"]
