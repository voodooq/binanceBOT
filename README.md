# BinanceBot V3.0 - 资管级量化交易系统

本项目是一个基于 Python 异步引擎（FastAPI + asyncio）与 React 现代化前端构建的币安（Binance）专业网格交易系统。V3.0 引入了**多账户支持**、**信封加密安全机制**、**WebSocket 实时监控集线器**以及**全栈容器化部署**。

## 🚀 核心特性 (V3.0 新增)
- **多账户管理**: 支持同时挂载多个 Binance 账户（实盘或 Testnet），且支持每个账户绑定独立的代理服务器。
- **资管级安全**: API Secret 采用信封加密 (Envelope Encryption)，私钥仅在内存中临时还原，禁止明文落地。
- **现代化 UI**: 基于 React + Tailwind CSS 的深色模式管理后台，实时观测挂单分布与收益曲线。
- **高性能引擎**: 采用 `uvloop` (Linux) 与 `orjson` 优化，支持高并发挂单与毫秒级事件响应。
- **生产就绪**: 内置 Nginx 反向代理、自动化 Docker 编排以及跨进程熔断开关 (Kill Switch)。

## 🛠️ 技术栈
- **后端**: Python 3.11, FastAPI, SQLAlchemy (异步), PostgreSQL, Redis
- **前端**: React 19, Vite, Tailwind CSS 4, React Query, Lucide Icons
- **架构**: Docker Compose, WebSockets, Redis Pub/Sub

## 📦 快速启动 (本地开发)

### 1. 克隆并安装依赖
```bash
# 后端
pip install -r requirements.txt
# 前端
cd frontend && npm install
```

### 2. 环境配置
复制 `.env.example` 为 `.env` 并填写必要信息（如数据库、加密主密钥等）。

### 3. 启动开发服务
```bash
# 后端
uvicorn src.main:app --reload
# 前端
cd frontend && npm run dev
```

## 🏗️ 生产环境部署 (推荐：Docker Compose)

### 1. 编译并启动全栈镜像
```bash
docker-compose up -d --build
```
系统将自动拉起：
- **FastAPI Backend (8000)**: 逻辑引擎与 API
- **Nginx Frontend (80)**: UI 界面与反代
- **PostgreSQL**: 持久化存储
- **Redis**: 事件总线与缓存

### 2. 访问地址
- 前端管理后台: `http://SERVER_IP`
- API 文档 (Swagger): `http://SERVER_IP/api/v1/openapi.json`

## ☁️ ClawCloud (VPS) 部署方案

如果您使用的是 ClawCloud 或类似的海外 VPS，可以按照以下步骤快速部署：

1. **环境初始化**:
   ```bash
   sudo apt update && sudo apt install docker.io docker-compose -g git -y
   ```
2. **下载代码**:
   ```bash
   git clone <YOUR_REPO_URL>
   cd binancebot
   ```
3. **配置参数**:
   - `mv .env.example .env` 
   - 修改 `MASTER_KEY` (32位强随机字符串) 及数据库密码。
   - **重要**: 设置 `BINANCE_PROXY` (如果是在受限地区)。
4. **一键启动**:
   ```bash
   docker-compose up -d --build
   ```

## 📂 项目结构
- `/src`: 后端核心逻辑（API, 模型, 策略引擎）
- `/frontend`: React 前端源码
- `/migrations`: Alembic 数据库迁移
- `/state`: 运行时策略持久化状态 (JSON)

## 🛡️ 安全注意事项
- **不要提交 .env 文件**: 生产环境下应妥善保管 `MASTER_KEY`，一旦丢失将无法还原 API Secret。
- **代理建议**: 建议在使用 Binance 时为每个机器人分配独立的静态代理以分散 IP 风险。

## ⚖️ 免责声明
量化交易存在风险，本项目仅供技术调研与学习使用。作者不对任何因使用本项目造成的财务损失负责。
