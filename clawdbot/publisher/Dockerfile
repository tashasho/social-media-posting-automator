FROM python:3.11-slim

# Create non-root user
RUN useradd -m -u 1002 publisher && \
    mkdir -p /data/drafts /data/approved /app && \
    chown -R publisher:publisher /data /app

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=publisher:publisher . .

# Switch to non-root user
USER publisher

# Expose Flask port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=5s \
    CMD curl -f http://localhost:5000/health || exit 1

CMD ["python", "webhook_receiver.py"]
