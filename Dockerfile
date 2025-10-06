FROM public.ecr.aws/lambda/python:3.11

# Build arguments for timestamp
ARG BUILD_TIMESTAMP
ARG BUILD_VERSION=latest

# Labels for metadata
LABEL build.timestamp="${BUILD_TIMESTAMP}"
LABEL build.version="${BUILD_VERSION}"
LABEL build.component="roblox-downloader"

WORKDIR ${LAMBDA_TASK_ROOT}

# Install system dependencies required for Playwright/Chromium
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
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium && \
    playwright install-deps chromium

# Copy application files
COPY download_roblox.py ${LAMBDA_TASK_ROOT}/download_roblox.py
COPY lambda_handler.py ${LAMBDA_TASK_ROOT}/lambda_handler.py

# Create output directory
RUN mkdir -p /downloads

# Create a build info file for runtime access
RUN echo "Build Timestamp: ${BUILD_TIMESTAMP}" > ${LAMBDA_TASK_ROOT}/build_info.txt && \
    echo "Build Version: ${BUILD_VERSION}" >> ${LAMBDA_TASK_ROOT}/build_info.txt && \
    echo "Component: roblox-downloader" >> ${LAMBDA_TASK_ROOT}/build_info.txt

# Set default output directory
ENV OUTPUT_DIR=/downloads

# Set headless mode for Docker (no display available)
ENV HEADLESS=true

# Set Lambda handler
CMD ["lambda_handler.handler"]

