# Build the wheel in one stage, install it in a clean one, so build tools and
# the Poetry install never reach the runtime image.

FROM python:3.13-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir poetry==2.4.2
COPY pyproject.toml ./
COPY wordle ./wordle
RUN poetry build --format wheel

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Runs as a non-root user; nothing in the image needs to be writable.
RUN useradd --system --uid 10001 --create-home --shell /usr/sbin/nologin wordle
WORKDIR /app

COPY --from=build /src/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

USER wordle
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request as u,sys; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)"

# One worker only: games live in this process's memory, so a second worker
# would not see them. See DEPLOYMENT.md.
CMD ["uvicorn", "wordle.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
