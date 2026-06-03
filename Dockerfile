FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install --no-install-recommends -y \
        build-essential \
        gcc \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /install
COPY requirements.txt ./
RUN pip install --prefix=/install/deps -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/install/deps/lib/python3.12/site-packages:/app \
    PATH=/install/deps/bin:$PATH

RUN apt-get update \
 && apt-get install --no-install-recommends -y \
        curl \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 appuser \
 && useradd  --system --uid 10001 --gid 10001 --home /app --shell /usr/sbin/nologin appuser

COPY --from=builder /install/deps /install/deps

WORKDIR /app
COPY el ./el
COPY scripts ./scripts
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
 && mkdir -p /app/data \
 && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "el.web:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
