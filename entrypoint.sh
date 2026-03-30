#!/bin/bash
set -e

echo "Running database migrations..."
# 确保数据库已准备好接收连接
# 在本地 docker-compose 中，虽然有 depends_on，但数据库进程启动到就绪可能仍有延迟
sleep 3

alembic upgrade head

echo "Starting backend server..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000
