# ==============================================================================
# WebGuardian AI - Production Dockerfile for Render.com / Cloud Deployment
# ==============================================================================
# Uses Microsoft Playwright Python base image with pre-installed Chromium & OS deps.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Set working directory
WORKDIR /app

# Prevent Python from writing pyc files and buffer stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY demo-site/ ./demo-site/
COPY demo-site_backup/ ./demo-site_backup/

# Create runtime storage directories
RUN mkdir -p storage/screenshots reports

# Expose default FastAPI port
EXPOSE 8000

# Start production Uvicorn server binding to 0.0.0.0 for cloud hosting
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
