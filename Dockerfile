FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip3 install --upgrade pip && pip3 install -r /app/requirements.txt

COPY . /app

# Add a non-root user for safety
RUN adduser --disabled-password --gecos '' appuser || true
RUN mkdir -p /app/staticfiles && chown -R appuser:appuser /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser

EXPOSE ${PORT:-8080}

ENTRYPOINT ["/entrypoint.sh"]
