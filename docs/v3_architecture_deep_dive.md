# BinanceBot V3.0 深度技术解析与操作手册

本手册通过第一性原理剖析了 **BinanceBot V3.0** 从个人脚本向工业级量化产品进阶的核心演进路径与底层价值。

## 一、 核心架构：解耦与高并发自愈

### 1. 行情与交易的徹底解耦 (IO Concurrency)
- **V2 痛点**：下单 REST 请求的同步阻塞导致 WebSocket 缓冲区堆积，引发断线重连。
- **V3 方案**：`onPrice` 仅作为逻辑触发源，更新水位。下单指令通过异步 `Task` 派发。
- **价值**：确保在极端波动行情下，主行情流不掉线，交易指令零滞后。

### 2. 后台持久化与流聚合中心 (P4 Optimization)
- **自愈机制**：基于 FastAPI `lifespan` 钩子，服务重启后通过 `init_and_resume_all` 自动扫描 `RUNNING` 数据库状态并异步恢复。
- **流聚合 (Stream Aggregator)**：多 Bot 共享单一 Symbol 的 WebSocket 连接，将网络句柄消耗从 $O(n)$ 降至 $O(1)$，彻底消除“性能消耗尽”的崩溃隐患。

---

## 二、 策略算法逻辑：网格与对冲

### 1. 自动底仓构建 (Bootstrapping)
在启动 **中性/做多** 策略时，系统自动演算卖盘区所需的币量：
- **公式**：$\text{Required\_Base\_Asset} = \sum_{i \in \text{Sell\_Grids}} (\text{Grid\_Price}_i \times \text{Grid\_Qty}_i)$
- **价值**：自动平衡可用余额，免除用户手动补仓/换币的操作。

### 2. 期现平衡器 (DeltaBalancer)
- **逻辑**：监控现货与 1x 做空合约的净敞口 (Delta)。
- **阈值控制**：默认 0.5% 灵敏度，超出则自动触发合约对冲补单。
- **视觉反馈**：通过 WebSocket 将偏差率事实推送至 `BotDetail` 仪表盘。

---

## 三、 安全、合规与代理池

- **GeoCheckService**：强制地域 IP 地理位置脱敏校验，防止受限地区 API 账号风险。
- **ProxyScheduler**：分布式代理池设计，通过 SOCKS5 代理轮询均衡下单频率压力，支持大规模集群水平扩展。

---

## 四、 进阶路线图 (Roadmap to V4.0)

基于当前架构，未来将重点围绕以下三点进行迭代：

1. **📊 数据库分表 (Sharding)**：将成交明细等海量数据迁移至分析库（如 ClickHouse），减轻主库 IO 压力。
2. **👻 影子交易 (Shadow Trading)**：支持基于 `MockBinanceClient` 的全仿真并轨运行，实时计算实盘滑点偏差。
3. **🧮 数学模型推演**：针对 `DeltaBalancer` 的再平衡算法，引入更精细的 Alpha 指数调整与自适应动态阈值。

---

## 五、 后期巡检 Checklist

- [ ] **WS 活性**：面板价格跳动频率是否与币安 APP 保持秒级同步。
- [ ] **Redis 状态**：使用 `redis-cli monitor` 确认跨进程事件总线无堆积。
- [ ] **资产校验**：确认 `Investment Auto-Calc` 已准确预留 0.2% 以上的手续费缓冲。
