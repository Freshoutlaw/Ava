# Ava — Dockerfile  (Tier 11)
# Build:   docker build -t ava .
# Run:     docker run -d --env-file .env --name ava ava
# With compose: docker-compose up -d

FROM python:3.11-slim

# System deps for audio (headless TTS only — no mic in container)
RUN apt-get update && apt-get install -y \
    curl ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project
COPY . .

# Install Python deps (no sounddevice/pyaudio in headless mode)
RUN pip install --no-cache-dir \
    groq \
    python-dotenv \
    requests \
    deepgram-sdk \
    miniaudio \
    numpy \
    websockets \
    schedule

# Data directory
RUN mkdir -p /app/data

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:7333/ || exit 1

# Expose web UI and WebSocket ports
EXPOSE 7333 7334

# Run in headless + web UI mode
ENV AVA_HEADLESS=1
CMD ["python", "ava.py", "--headless", "--no-ui", "--web-ui"]
