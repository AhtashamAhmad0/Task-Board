FROM python:3.15-slim

# unbuffered logs show up instantly in `docker logs`
ENV PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    DB_PATH=/data/tasks.db

WORKDIR /app

COPY server.py .
COPY static ./static

# run as a non-root user, with a writable folder for the database
RUN useradd --create-home appuser \
    && mkdir /data \
    && chown appuser:appuser /data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["python", "server.py"]