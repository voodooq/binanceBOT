#!/bin/bash
set -e

# --- 自动构造单体版必需的环境变量 ---
# 将用户在面板填写的 JWT_SECRET 映射到程序需要的 JWT_SECRET_KEY
export JWT_SECRET_KEY="${JWT_SECRET:-$JWT_SECRET_KEY}"

# 构造内部数据库连接串 (单体版固定访问 127.0.0.1)
# 注意：V3 后端使用 asyncpg
if [ -z "$DATABASE_URL" ]; then
    export DATABASE_URL="postgresql+asyncpg://postgres:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB:-binancebot}"
fi

# 构造内部 Redis 连接串
if [ -z "$REDIS_URL" ]; then
    export REDIS_URL="redis://127.0.0.1:6379/0"
fi


# 根据 Launchpad 的设定，如果从宿主机挂载了一个空的卷进来，它的权限会被改成 root 或者 777。
# 这会导致严格的 PostgreSQL 内核拒绝启动并报错："Data directory must not be owned by root" 或 "has group or world access"
echo "Fixing PostgreSQL mount permissions..."
chown -R postgres:postgres /var/lib/postgresql/15/main
chmod 700 /var/lib/postgresql/15/main

# 如果挂载卷内没有 PG_VERSION 文件，说明还不是一个有效的数据库集群，必须初始化
if [ ! -s "/var/lib/postgresql/15/main/PG_VERSION" ]; then
    echo "Cleaning up cloud storage artifacts like lost+found..."
    rm -rf /var/lib/postgresql/15/main/lost+found || true
    rm -rf /var/lib/postgresql/15/main/.* 2>/dev/null || true
    
    echo "Initializing empty PostgreSQL data directory..."
    su - postgres -c "/usr/lib/postgresql/15/bin/initdb -D /var/lib/postgresql/15/main"
    # 初始化后把我们之前准备好的配置文件写进去
    echo "host all  all    0.0.0.0/0  md5" >> /var/lib/postgresql/15/main/pg_hba.conf
    echo "listen_addresses='*'" >> /var/lib/postgresql/15/main/postgresql.conf
fi

# 1. 启动必须的基础服务
/etc/init.d/redis-server start
/etc/init.d/postgresql start

# 确保数据库内部密码与环境变量同步 (这一步必须在数据库启动后、迁移执行前)
echo "Synchronizing database password..."
su - postgres -c "psql --command \"ALTER USER postgres WITH PASSWORD '${POSTGRES_PASSWORD}';\""
su - postgres -c "createdb -O postgres binancebot || true"

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
