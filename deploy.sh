#!/bin/bash

# --- BinanceBot V3.0 一键部署脚本 ---
# 适用环境：ClawCloud / Ubuntu / Debian / CentOS (需预装 Docker)

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}>>> 开始部署 BinanceBot V3.0...${NC}"

# 1. 检查环境变量文件
if [ ! -f .env ]; then
    echo -e "${YELLOW}警告: 未找到 .env 文件，正在从模板创建...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}请记得在部署完成后手动按需修改 .env 中的 MASTER_KEY 和数据库密码!${NC}"
fi

# 2. 停止并清理旧容器
echo -e "${YELLOW}>>> 正在停止现有服务 (如果有)...${NC}"
docker-compose down || true

# 3. 编译并拉起新版本
echo -e "${GREEN}>>> 正在构建并启动全栈镜像 (后台模式)...${NC}"
docker-compose up -d --build

# 4. 确认服务状态
echo -e "${GREEN}>>> 部署完成! 正在检查服务存活状态...${NC}"
sleep 5
docker ps | grep bb_

echo -e "------------------------------------------------"
echo -e "${GREEN}部署成功!${NC}"
echo -e "前端面板地址: http://$(curl -s ifconfig.me)"
echo -e "API 文档地址: http://$(curl -s ifconfig.me)/api/v1/openapi.json"
echo -e "------------------------------------------------"
echo -e "提示: 使用 'docker-compose logs -f backend' 查看运行日志"
