# ============================================================================
# Persian License Plate Recognition — Multi-Stage Dockerfile
# ============================================================================
# Build:  docker build -t persian-lpr-api:latest .
# Run:    docker run -p 8000:8000 -v ./weigths:/app/weigths:ro persian-lpr-api
# ============================================================================

ARG PYTHON_VERSION=3.11

# ── Stage 1: Dependencies ──────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS deps

ARG TORCH_VERSION=cpu

# System libraries required by OpenCV and image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

# Install PyTorch (CPU-only to keep image small) then remaining deps
RUN if [ "$TORCH_VERSION" = "cpu" ]; then \
        pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu; \
    fi && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# ── Stage 2: Application ───────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS app

# Reinstall minimal runtime system libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Copy application source code
COPY api.py .
COPY db.py .
COPY schemas.py .
COPY camera_manager.py .
COPY plate_metadata.py .
COPY error_handler.py .
COPY plate_reference.py .
COPY routers/ ./routers/
COPY auth/ ./auth/
COPY retention/ ./retention/
COPY deep_text_recognition_benchmark/ ./deep_text_recognition_benchmark/
COPY verification.py .

# Create directories for runtime volumes
RUN mkdir -p /app/weigths /app/db /app/io/output && \
    chown -R appuser:appuser /app

# Environment configuration
ENV MODEL_DIR="/app/weigths"
ENV DATABASE_DIR="/app/db"
ENV OUTPUT_DIR="/app/io/output"
ENV PORT="8000"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Switch to non-root user
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
