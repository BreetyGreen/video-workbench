FROM python:3.11.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY dingtalk_connector ./dingtalk_connector
RUN pip install --no-cache-dir .

CMD ["python", "-m", "dingtalk_connector.main"]
