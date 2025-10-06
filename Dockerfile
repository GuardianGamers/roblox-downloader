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
RUN yum install -y \
    wget \
    ca-certificates \
    liberation-fonts \
    alsa-lib \
    at-spi2-atk \
    atk \
    at-spi2-core \
    cups-libs \
    dbus-libs \
    libdrm \
    mesa-libgbm \
    gtk3 \
    nspr \
    nss \
    libwayland-client \
    libXcomposite \
    libXdamage \
    libXfixes \
    libxkbcommon \
    libXrandr \
    xdg-utils \
    && yum clean all

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

