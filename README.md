# 币安量化交易机器人 (Binance Grid Trading Bot)

本项目是一个基于 Python 异步架构（`asyncio` + `BinanceSocketManager`）实现的币安（Binance）专属量化网格交易机器人。支持实时行情监听、订单状态追踪、Telegram 通知以及持久化状态管理。

## 🌟 主要功能

- **网格交易策略**：自动化高抛低吸，支持自定义网格上限、下限、网格数等参数。
- **异步与高并发**：底层采用 `aiohttp` 和 `python-binance` 异步流，实现毫秒级行情与订单响应。
- **WebSocket 数据流**：通过多路复用或独立 WebSocket 监听实时价格和 `userDataStream` (订单状态)。
- **持久化与容灾**：运行状态落盘，Docker 环境下通过 Volume 挂载，支持进程崩溃、重启后自动恢复交易进度。
- **多端通知**：内建 Telegram Bot 支持，实时播报挂单、成交、策略启停及异常告警。
- **Docker 化部署**：提供完整的 `Dockerfile` 与 `docker-compose.yml`，一键部署应用及依赖（PostgreSQL、Redis）。

## 🛠️ 技术栈

- **后端**：Python 3.10+, `asyncio`, `python-binance`, `FastAPI` (预留面板接口)
- **数据库/缓存**：PostgreSQL 15, Redis 7 (预留为 V3 资管级和全局状态共享准备)
- **部署发布**：Docker, Docker Compose
- **代码规范**：统一应用 PEP8，核心逻辑添加完整类型注解与详细中文注释

## 🚀 部署与运行说明

### 1. 环境准备

确保系统已安装 Docker 与 Docker Compose（如果选择本地运行，则需要 Python 3.10+ 环境，并安装 `requirements.txt` 所需依赖）。项目内部采用虚拟化网络防止端口冲突。

### 2. 配置文件

复制示例配置文件，并填入相应的 API Key 和 Telegram 配置：

```bash
cp .env.example .env
```

**关键配置项（`.env`）：**
- `BINANCE_API_KEY` / `BINANCE_API_SECRET`：您的币安 API 密钥（建议使用只具备交易权限的子账号）。
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`：用于接收日志与告警通知。
- `PROXY_URL`（如处于国内环境）：机器人会自动为所有底层网络请求配置代理。

### 3. 一键启动 (推荐)

使用 Docker Compose 会同时启动机器人主程序、PostgreSQL 与 Redis。

```bash
# 以后台模式运行
docker-compose up -d

# 查看运行日志
docker-compose logs -f binance-bot
```

### 4. 本地环境测试

若需进行本地开发与调试：

```bash
# 建立虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 运行机器人
python main.py

# (可选) 运行回测或清理测试网脚本
python cleanup.py
```

## 📂 项目结构

```text
├── src/                # 核心源代码
│   ├── api/            # API 路由与端点
│   ├── config/         # 环境与配置管理
│   ├── db/             # 数据库模型与会话管理
│   ├── exchanges/      # 交易所客户端 (币安 API 封装)
│   ├── models/         # 数据库 ORM 模型定义
│   ├── strategies/     # 交易策略实现 (网格策略核心)
│   └── utils/          # 日志、通知、限流等通用工具
├── tests/              # 单元与集成测试目录
├── migrations/         # Alembic 数据库迁移脚本
├── .env.example        # 配置示例文件
├── docker-compose.yml  # Docker Compose 编排文件
├── Dockerfile          # Docker 镜像构建文件
├── main.py             # 交易机器人主入口程序
└── cleanup.py          # 测试环境一键清理脚本
```

## 🛡️ 安全规范与开发约定

本项目严格遵循以下安全与开发原则：
- **安全第一**：核心敏感数据（API Key 等）仅通过本地环境变量加载，**严禁将密钥等凭证上传至代码仓库**。
- **规范先行**：保持高质量的文档注释与类型提示，所有新增业务逻辑必须独立于框架耦合。
- **稳健运行**：任何外部 API 交互必须经过 `RateLimiter`（限流器）统领，避免触发交易所风控机制或引起服务宕机。
