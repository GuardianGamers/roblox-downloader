FROM python:3.11-slim

# Build arguments for timestamp
ARG BUILD_TIMESTAMP
ARG BUILD_VERSION=latest

# Labels for metadata
LABEL build.timestamp="${BUILD_TIMESTAMP}"
LABEL build.version="${BUILD_VERSION}"
LABEL build.component="roblox-downloader"

WORKDIR /app

# Install system dependencies required for Playwright/Chromium and Pillow
RUN apt-get update && apt-get install -y \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    xauth \
    libjpeg62-turbo \
    libpng16-16 \
    libwebp7 \
    libtiff6 \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium && \
    playwright install-deps chromium

# Copy application files
COPY download_roblox.py /app/download_roblox.py
COPY ecs_task.py /app/ecs_task.py
COPY update_gameservers.py /app/update_gameservers.py
COPY roblox_charts_scraper.py /app/roblox_charts_scraper.py
COPY gamecategories.json /app/gamecategories.json

# Create output directory
RUN mkdir -p /downloads

# Create a build info file for runtime access
RUN echo "Build Timestamp: ${BUILD_TIMESTAMP}" > /app/build_info.txt && \
    echo "Build Version: ${BUILD_VERSION}" >> /app/build_info.txt && \
    echo "Component: roblox-downloader" >> /app/build_info.txt

# Set default output directory
ENV OUTPUT_DIR=/downloads

# Set headless mode (back to true for now)
ENV HEADLESS=true
ENV PYTHONUNBUFFERED=1

# Run the ECS task script directly
CMD ["python", "/app/ecs_task.py"]

