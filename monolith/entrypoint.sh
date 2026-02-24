#!/bin/bash
set -e

# 根据 Launchpad 的设定，如果从宿主机挂载了一个空的卷进来，它的权限会被改成 root 或者 777。
# 这会导致严格的 PostgreSQL 内核拒绝启动并报错："Data directory must not be owned by root" 或 "has group or world access"
echo "Fixing PostgreSQL mount permissions..."
chown -R postgres:postgres /var/lib/postgresql/15/main
chmod 700 /var/lib/postgresql/15/main

# 如果挂载卷是非常空的，我们还要触发一下初始化
if [ -z "$(ls -A /var/lib/postgresql/15/main)" ]; then
    echo "Initializing empty PostgreSQL data directory..."
    su - postgres -c "/usr/lib/postgresql/15/bin/initdb -D /var/lib/postgresql/15/main"
    # 初始化后把我们之前准备好的配置文件写进去
    echo "host all  all    0.0.0.0/0  md5" >> /var/lib/postgresql/15/main/pg_hba.conf
    echo "listen_addresses='*'" >> /var/lib/postgresql/15/main/postgresql.conf
    # 把之前自动创建的密码补上
    /etc/init.d/postgresql start
    sleep 3
    su - postgres -c "psql --command \"ALTER USER postgres WITH PASSWORD 'postgres';\""
    su - postgres -c "createdb -O postgres binancebot || true"
    /etc/init.d/postgresql stop
fi

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
