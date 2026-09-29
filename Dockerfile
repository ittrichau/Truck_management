FROM python:3.12-slim

# Create non-root user with a stable UID/GID for host bind-mount permissions.
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

# Install WeasyPrint system dependencies (required for PDF generation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 libffi-dev shared-mime-info \
    fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh && chown app:app docker-entrypoint.sh

# Create log directory with proper permissions
RUN mkdir -p /var/log/app && chown -R app:app /app /var/log/app

EXPOSE 5000

# Switch to non-root user
USER app

# Entrypoint handles migrations + gunicorn startup
ENTRYPOINT ["./docker-entrypoint.sh"]
