FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

# 纯标准库实现，无第三方依赖；仅复制源码与测试
COPY app/ ./app/
COPY tests/ ./tests/
COPY scripts/ ./scripts/

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --start-period=3s --retries=5 \
    CMD python scripts/verify_smoke.py http://127.0.0.1:8080/healthz

CMD ["python", "-m", "app.server"]
