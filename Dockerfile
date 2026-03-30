# --- Backend Build Stage ---
FROM python:3.11-slim as backend

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制整个源码目录
COPY . .

# 复制启动脚本
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# 创建必要的持久化目录
RUN mkdir -p /app/state /app/logs

# 启动命令使用启动脚本
ENTRYPOINT ["./entrypoint.sh"]
