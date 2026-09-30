FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# 纯标准库应用，无需安装第三方依赖
COPY app ./app
COPY static ./static
COPY tests ./tests
COPY scripts ./scripts

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --start-period=3s --retries=5 \
    CMD python -c "import json,os,urllib.request;port=os.environ.get('PORT','8080');r=urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=3);assert json.load(r)['status']=='ok'"

CMD ["python", "-m", "app.server"]
