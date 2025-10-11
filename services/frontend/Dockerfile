# ========================================
# Pizza Order System - Frontend Service Dockerfile
# Event-Driven Saga Architecture
# ========================================

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production
ENV SERVICE_NAME=frontend-service

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Установка k6 для нагрузочного тестирования
RUN apt-get update && \
    apt-get install -y gnupg ca-certificates curl && \
    mkdir -p /etc/apt/keyrings && \
    curl -s https://dl.k6.io/key.gpg | gpg --dearmor -o /etc/apt/keyrings/k6.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/k6.gpg] https://dl.k6.io/deb stable main" | tee /etc/apt/sources.list.d/k6.list && \
    apt-get update && \
    apt-get install -y k6

# Копируем requirements.txt из родительской папки
COPY requirements.txt requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Копируем shared из родительской папки
COPY shared/ shared/

# Копируем все файлы текущей папки (frontend)
COPY frontend/ .

# k6-скрипты монтируются через volume в docker-compose.yml
# Не нужно копировать, так как есть volume mapping: ./load-testing:/app/load-testing

# Copy and setup init script
COPY shared/init_logs.sh /usr/local/bin/init_logs.sh
RUN chmod +x /usr/local/bin/init_logs.sh

# Create logs directory
RUN mkdir -p logs

# Create non-root user for security
RUN groupadd -r pizza && useradd -r -g pizza pizza
RUN chown -R pizza:pizza /app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Expose port
EXPOSE 5000

# Run the application with init script
CMD ["/usr/local/bin/init_logs.sh", "python", "app.py"]