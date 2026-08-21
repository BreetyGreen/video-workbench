FROM python:3.11.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl espeak-ng ffmpeg mediainfo fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN mkdir -p app \
    && touch app/__init__.py \
    && pip install --no-cache-dir .
COPY app ./app

ENV HF_HUB_DISABLE_XET=1

EXPOSE 8130
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8130"]
