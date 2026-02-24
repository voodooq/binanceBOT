#!/bin/bash
set -e

# 1. 启动必须的基础服务
/etc/init.d/redis-server start
/etc/init.d/postgresql start

# 给数据库一点时间准备就绪
sleep 3

# 2. 执行数据库自动迁移（Alembic）
echo "Running database migrations..."
cd /app
/app/venv/bin/alembic upgrade head

# 3. 停止通过 init.d 启动的服务，转交给 supervisord 接管前台运行
/etc/init.d/redis-server stop
/etc/init.d/postgresql stop

echo "Starting all services via supervisord..."
exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisord.conf
