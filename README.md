# BinanceBot V3.0 - 资管级量化交易系统

BinanceBot V3.0 是一个基于 Python 异步后端与 React 前端构建的全栈量化交易系统，面向 Binance 交易场景，提供多账户管理、机器人编排、回测、实时监控、通知中心与容器化部署能力。

当前版本的主运行形态为：

- **后端 API**：FastAPI + asyncio
- **前端控制台**：React + Vite
- **基础设施**：PostgreSQL + Redis
- **实时通信**：WebSocket + Redis Pub/Sub

> 日常开发与部署请使用 `src.main:app`、`run.bat`、`run.sh` 或 `docker-compose`。
>
> **不要再直接运行仓库根目录的 `main.py` / `cleanup.py` 作为主启动方式**，那是历史 CLI 链路，已不再对应当前 V3 Web 平台架构。

---

## 🚀 核心能力

### 交易与策略
- **多账户 API Key 管理**：支持用户绑定多个 Binance API Key
- **策略类型**：当前内置 `grid`、`hedge`、`neutral`
- **机器人全生命周期管理**：创建、启动、停止、强平、删除、成交记录查询
- **状态恢复**：服务启动时自动恢复数据库中处于 `RUNNING` 的机器人
- **主网保护开关**：默认禁止主网真实交易，需显式启用 `ALLOW_LIVE_TRADING=true`

### 安全与认证
- **Envelope Encryption 信封加密**：API Secret 不以明文落地
- **JWT 登录认证**
- **2FA 双因素认证**
- **配置级主网开关与环境隔离**

### 平台能力
- **Dashboard 概览**
- **市场行情查询**
- **回测引擎与回测接口**
- **通知中心与通知设置**
- **WebSocket 实时推送**
- **Docker Compose / 单体镜像部署支持**

---

## 🛠️ 技术栈

### 后端
- Python 3.11
- FastAPI
- SQLAlchemy Async
- Alembic
- PostgreSQL
- Redis
- python-binance
- Pydantic / pydantic-settings

### 前端
- React 19
- Vite 7
- TypeScript
- Tailwind CSS 4
- TanStack React Query
- Zustand
- Lucide React

### 部署与运行
- Docker Compose
- Nginx
- Uvicorn
- Redis Pub/Sub
- WebSocket

---

## 📡 当前 API 模块

后端默认 API 前缀为 `/api/v1`，当前已启用的主要模块包括：

- `auth`：注册、登录、2FA
- `keys`：API Key 管理
- `bots`：机器人管理
- `dashboard`：看板概览
- `market`：市场价格查询
- `backtest`：回测
- `notifications`：通知中心
- `ws`：WebSocket 实时推送，地址为 `/api/v1/ws`

---

## 🖥️ 前端页面概览

当前前端主要包含：

- 登录 / 注册
- Dashboard
- API Key 管理
- 机器人列表
- 创建机器人
- 机器人详情
- 实时监控、回测弹层、通知抽屉

---

## 📦 环境变量说明

项目默认读取根目录 `.env` 文件，可从 `.env.example` 或 `.env.prod.example` 复制生成。

### 最关键的变量

| 变量名 | 说明 |
|---|---|
| `MASTER_ENCRYPTION_KEY` | 主密钥，必须是 **32 字节 url-safe base64** |
| `JWT_SECRET_KEY` | JWT 签名密钥，至少 32 字符 |
| `DATABASE_URL` | PostgreSQL 异步连接串 |
| `REDIS_URL` | Redis 连接串 |
| `ALLOW_LIVE_TRADING` | 是否允许主网真实交易，默认 `false` |
| `BINANCE_TESTNET` | 默认是否使用测试网，建议本地开发保持 `true` |
| `IGNORE_GEO_CHECK` | 是否忽略地域合规检查 |

### 开发环境示例

```env
ENVIRONMENT=development
MASTER_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
JWT_SECRET_KEY=CHANGE_ME_TO_A_LONG_RANDOM_SECRET_KEY_32_PLUS
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/binancebot
REDIS_URL=redis://127.0.0.1:6379/0
ALLOW_LIVE_TRADING=false
BINANCE_TESTNET=true
```

### 生成 `MASTER_ENCRYPTION_KEY`

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> V3 的交易所 API Key 不通过 `.env` 注入。
>
> **API Key 是用户登录后在 Web 控制台中管理的。**

---

## ⚡ 快速启动

### 方式一：Docker Compose 全栈启动

适合本地完整体验或服务器部署。

#### 1. 准备环境变量
```bash
cp .env.example .env
```

按需修改 `.env` 中的核心配置，至少确认：
- `MASTER_ENCRYPTION_KEY`
- `JWT_SECRET_KEY`
- `DATABASE_URL`
- `REDIS_URL`

#### 2. 启动完整服务
```bash
docker-compose up -d --build
```

会启动以下服务：

- `backend`：FastAPI 后端
- `frontend`：Nginx + 前端静态资源
- `postgres`：PostgreSQL
- `redis`：Redis

#### 3. 访问地址
- 前端控制台：`http://SERVER_IP`
- OpenAPI JSON：`http://SERVER_IP/api/v1/openapi.json`

> `backend` 容器启动时会自动执行 `alembic upgrade head`。

---

### 方式二：本地开发模式

适合前后端联调与功能开发。

#### 1. 准备后端依赖
```bash
pip install -r requirements.txt
```

#### 2. 准备前端依赖
```bash
cd frontend && npm install
```

#### 3. 启动本地基础设施
如果本机还没有 PostgreSQL / Redis，可直接使用仓库内的 Compose 只拉起基础服务：

```bash
docker-compose up -d postgres redis
```

#### 4. 启动开发环境

##### Windows
直接运行：

```powershell
./run.bat
```

`run.bat` 当前会执行以下动作：
1. 检查 `.env`
2. 激活 Conda 环境
3. 执行 `alembic upgrade head`
4. 启动前端 Vite 开发服务器
5. 启动后端 Uvicorn 服务

> `run.bat` 中默认写死了：
> - `CONDA_PATH=D:\anaconda3`
> - `ENV_NAME=binancebot`
>
> 如果你的 Conda 安装路径或环境名不同，请先修改脚本中的这两个变量。

##### Linux / macOS
```bash
chmod +x run.sh
./run.sh
```

##### 手动启动
如果你不想用脚本，也可以手动分别启动：

```bash
# 迁移数据库
alembic upgrade head

# 启动后端
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

另开一个终端：

```bash
cd frontend
npm run dev
```

#### 5. 本地访问地址
- 前端：`http://127.0.0.1:5173`
- 后端 API：`http://127.0.0.1:8000`
- Swagger UI：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/api/v1/openapi.json`

> Vite 已代理 `/api` 与 `/api/v1/ws`，本地前端调试时可直接使用同源路径访问 API 和 WebSocket。

---

## ☁️ 部署方式说明

### 方案 A：标准 Docker Compose 部署
适用于常规 VPS / 云主机，推荐优先使用。

核心命令：

```bash
bash deploy.sh
```

脚本会：
- 检查 `.env`
- 拉起 PostgreSQL / Redis / Backend / Frontend
- 自动构建并后台运行服务

### 方案 B：单体镜像 / 面板部署
仓库同时提供单体部署支持，相关文件位于：

- `monolith/Dockerfile.standalone`
- `monolith/entrypoint.sh`
- `monolith/supervisord.conf`
- `DEPLOY_CLAWCLOUD.md`

适合只允许配置单镜像的可视化部署平台。

---

## 📂 项目结构

```text
.
├─ src/                 # 后端核心代码
│  ├─ api/              # API 路由
│  ├─ core/             # 配置与安全
│  ├─ db/               # 数据库连接
│  ├─ engine/           # 运行引擎、流聚合、WS 推送
│  ├─ exchanges/        # Binance 通信封装
│  ├─ models/           # ORM 模型
│  ├─ schemas/          # Pydantic Schema
│  ├─ services/         # 业务服务
│  └─ strategies/       # 策略实现
├─ frontend/            # React 前端
├─ migrations/          # Alembic 迁移
├─ docs/                # 文档
├─ monolith/            # 单体镜像部署相关文件
├─ scripts/             # 运维/修复脚本
├─ run.bat              # Windows 本地开发启动脚本
├─ run.sh               # Linux/macOS 本地开发启动脚本
└─ docker-compose.yml   # 容器编排
```

---

## 🧪 开发注意事项

### 1. 不要再使用旧 CLI 启动链路
如果你看到类似报错：

- `'Settings' object has no attribute 'proxy'`
- `BINANCE_API_KEY 未配置，请在 .env 文件中设置真实的 API Key`

通常说明你运行到了旧版根目录 `main.py` / `cleanup.py` 启动链路。

**正确做法：**
- 使用 `./run.bat`
- 或使用 `./run.sh`
- 或直接执行 `python -m uvicorn src.main:app --reload`

### 2. 本地迁移失败
如果执行 `alembic upgrade head` 失败，优先检查：
- PostgreSQL 是否已启动
- `DATABASE_URL` 是否正确
- Redis 是否已启动
- `.env` 是否已正确填写

### 3. 前端没有自动启动
`run.bat` / `run.sh` 只有在以下条件满足时才会自动启动前端：
- 已执行 `cd frontend && npm install`
- 机器上有 `npm`
- `frontend/node_modules` 已存在

---

## 🔐 安全建议

- 不要提交真实 `.env`
- 妥善离线保存 `MASTER_ENCRYPTION_KEY`
- 生产环境默认保持 `ALLOW_LIVE_TRADING=false`
- 建议先使用测试网验证流程
- 对外部署时为前端、后端与数据库设置最小暴露面
- Binance API 建议按账户隔离、按用途分权

---

## 💻 服务器建议配置

| 配置项 | 最低要求（体验/测试） | 推荐配置（生产环境） |
|---|---:|---:|
| CPU | 1 vCPU | 2 vCPU |
| 内存 | 1 GB（建议额外配置 1G Swap） | 2 GB+ |
| 磁盘 | 10 GB | 20 GB+ SSD |
| 网络 | 可访问 Binance API | 稳定海外节点 |

> 如果使用单体镜像且主机内存仅 1GB，建议提前配置 Swap，避免服务启动峰值触发 OOM。

---

## ⚖️ 免责声明

量化交易具有高风险。本项目仅供技术研究、学习与系统开发参考，不构成任何投资建议。使用者需自行承担因部署、配置、策略运行或市场波动所导致的一切风险与损失。