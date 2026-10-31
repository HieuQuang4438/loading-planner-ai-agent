# Image of the web app (docs/product/architecture.md §8). Build context = repo
# root; the deploy builds it on the VM from `git archive <ref>`. Only src/ goes in: no user data, no eval sets.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLANNER_DB=/data/app.db \
    # Proxy headers are trusted only from the compose network (subnet fixed in compose.yaml); 127.0.0.1 if run alone.
    FORWARDED_ALLOW_IPS=127.0.0.1

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir /data /app \
    && chown app:app /data /app

WORKDIR /app
COPY --chown=app:app requirements.txt ./
RUN pip install -r requirements.txt
COPY --chown=app:app src ./src

USER app
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=3).read()"]

# `sh -c exec`: uvicorn replaces the shell and is PID 1 (gets SIGTERM); the shell expands the variable.
CMD ["sh", "-c", "exec uvicorn --factory src.web.service.app:create_app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\""]
