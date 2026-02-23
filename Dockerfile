# 使用 Python 3.11 作为基础镜像 (与你的后端规范 ≥3.10 一致)
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量，防止 Python 缓冲 stdout 和 stderr，以及生成 .pyc 文件
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 更新系统依赖并清理缓存，保持镜像极小
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# 优先复制 requirements.txt 以利用 Docker 缓存机制
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码 (受 .dockerignore 控制)
COPY . .

# 创建必要的持久化目录，防止由于挂载导致的权限问题
RUN mkdir -p /app/state /app/logs

# 在容器启动前，可以通过 ENTRYPOINT 先执行 cleanup，如果不需要清理，直接 CMD 启动
# 这里采用 CMD，默认执行机器人主程序
CMD ["python", "main.py"]
