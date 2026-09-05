# syntax=docker/dockerfile:1.7

# Build the wheel in one stage and install it in a clean one, so Poetry and
# the build tools never reach the image that runs in production.

FROM python:3.13-slim AS build

WORKDIR /src
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir poetry==2.4.2

COPY pyproject.toml ./
COPY wordle ./wordle
RUN poetry build --format wheel


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    WORDLE_DATA_DIR=/data

# A fixed non-root uid, so files on the mounted volume have a stable owner
# whichever host this runs on. No home directory and no shell: this account
# exists to own a process, not to be logged into.
RUN set -eux; \
    groupadd --system --gid 10001 wordle; \
    useradd --system --uid 10001 --gid wordle --no-create-home \
            --shell /usr/sbin/nologin wordle; \
    install -d -o wordle -g wordle -m 0750 /data

WORKDIR /app

COPY --from=build /src/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl \
    && rm -rf /tmp/*.whl /root/.cache

# Everything above ran as root. Nothing below does.
USER 10001:10001

# Games live here. Declared so an unmounted run still works, though the data
# is then lost with the container.
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u,sys; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)"]

# One worker: SQLite plus a single writer is the intended shape here. See
# DEPLOYMENT.md before raising it.
CMD ["uvicorn", "wordle.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
