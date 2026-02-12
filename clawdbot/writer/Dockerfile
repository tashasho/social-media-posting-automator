FROM python:3.11-slim

# Create non-root user
RUN useradd -m -u 1000 clawdbot && \
    mkdir -p /data/drafts /app/rag && \
    chown -R clawdbot:clawdbot /data /app

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy code
COPY --chown=clawdbot:clawdbot . .

# Switch to non-root user
USER clawdbot

# Health check
HEALTHCHECK --interval=30s --timeout=3s \
    CMD python -c "import anthropic; print('ok')" || exit 1

CMD ["python", "writer.py"]
