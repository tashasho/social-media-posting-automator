FROM python:3.11-slim

# Create non-root user
RUN useradd -m -u 1001 scraper && \
    mkdir -p /data /app && \
    chown -R scraper:scraper /data /app

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=scraper:scraper . .

# Switch to non-root user
USER scraper

# Health check
HEALTHCHECK --interval=60s --timeout=5s \
    CMD python -c "import requests; print('ok')" || exit 1

CMD ["python", "scraper.py"]
