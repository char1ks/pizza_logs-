# ========================================
# Pizza Order System - Payment Mock Service Dockerfile
# Event-Driven Saga Architecture
# ========================================

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production
ENV SERVICE_NAME=payment-mock-service

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared modules
COPY shared/ shared/

# Copy payment mock service files
COPY payment-mock/ .

# Create logs directory
RUN mkdir -p logs

# Create non-root user for security
RUN groupadd -r pizza && useradd -r -g pizza pizza
RUN chown -R pizza:pizza /app
USER pizza

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Expose port
EXPOSE 5000

# Run the application
CMD ["python", "app.py"] 