# BinanceBot ClawCloud 部署方案

ClawCloud 凭借其在海外（如新加坡、日本）稳定的网络节点，是部署 BinanceBot 的理想平台。以下是推荐的部署步骤。

## 方案 A：使用 Docker Compose (推荐)

这种方案最灵活，适合具有标准 Ubuntu 或 Debian 镜像的 VPS。

### 1. 登录服务器并安装 Docker
```bash
# 更新并安装必要软件
sudo apt update && sudo apt install -y docker.io docker-compose git

# 启动 Docker 并设置开机自启
sudo systemctl enable --now docker
```

### 2. 克隆项目并配置
```bash
git clone https://github.com/voodooq/binanceBOT.git
cd binanceBOT

# 复制环境变量模板
cp .env.example .env
```

### 3. 编辑 .env 文件
使用 `nano .env` 或 `vim .env` 填写以下关键参数：
- `MASTER_ENCRYPTION_KEY`: 32位随机字符串（用于 API 密钥加密）。
- `JWT_SECRET`: 任意随机字符串。
- `POSTGRES_PASSWORD`: 数据库密码。
- `BINANCE_API_KEY`: 您的币安主密钥。
- `BINANCE_API_SECRET`: 您的币安私钥。

### 4. 启动系统
```bash
bash deploy.sh
```

---

## 方案 B：使用 ClawCloud App Launchpad (单镜像模式)

如果您使用的是 ClawCloud 的应用面板，只需选择镜像并配置环境变量即可。

### 1. 镜像设置
- **镜像地址**: `ghcr.io/voodooq/binancebot:v3` (或自行构建后推送的私有仓库地址)

### 2. 环境变量 (必填)
| 变量名 | 推荐值/说明 |
|--------|------------|
| `MASTER_ENCRYPTION_KEY` | 32位随机强密码 |
| `POSTGRES_PASSWORD` | 数据库密码 |
| `JWT_SECRET` | 随机字符串 |
| `APP_ENV` | `production` |

### 3. 持久化挂载 (Volume)
ClawCloud 实例重启可能会丢失数据，**务必**挂载以下路径：
- `/var/lib/postgresql/data` -> 映射到云硬盘

### 4. 端口放行
- 容器内端口: `80`
- 映射公网端口: `80` (或您喜欢的其他端口)

---

## ⚡ 性能优化建议 (针对 ClawCloud)
1. **Swap 虚拟内存**: 如果您的实例内存为 1GB，请执行 `sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile` 以防止内存溢出。
2. **Ping 测试**: 部署后在控制台执行 `curl -I https://api.binance.com/api/v3/ping`，确认延迟在 50ms 以内以获得最佳交易体验。
