FROM python:3.11-slim

# Include the cloned libraries in PYTHONPATH
ENV PYTHONPATH "${PYTHONPATH}:/app/lib/bamboo-engine:/app/lib/bamboo-engine/runtime/bamboo-pipeline"
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
# Including curl, git, procps (for ps command) and other tools for bamboo-engine shell execution
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    git \
    procps \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Install channel plugins if specified
ARG CHANNEL_PLUGINS=""
RUN if [ -n "$CHANNEL_PLUGINS" ]; then \
    pip install --no-cache-dir $CHANNEL_PLUGINS; \
    fi

# Create a non-root user and switch to it
RUN addgroup --system appuser && adduser --system --group appuser

COPY . .

# Change ownership of the app directory
RUN chown -R appuser:appuser /app




COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER appuser

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
