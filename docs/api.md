# API 接口文档

> 本文档涵盖 MingCe 系统所有对外接口，包括主服务 API、信号服务 API 以及飞书机器人指令。
> 主服务端口：**8000** — 信号服务端口：**8765**

---

## 目录

- [主服务 API（端口 8000）](#主服务-api端口-8000)
  - [1. 健康检查](#1-健康检查)
  - [2. 生成报告](#2-生成报告)
  - [3. 查询任务状态](#3-查询任务状态)
  - [4. 测试报告生成](#4-测试报告生成)
  - [5. 通用消息转发](#5-通用消息转发)
  - [6. 推送策略信号](#6-推送策略信号)
- [信号服务 API（端口 8765）](#信号服务-api端口-8765)
  - [1. 信号服务健康检查](#1-信号服务健康检查)
  - [2. 分析信号](#2-分析信号)
- [飞书机器人 @指令](#飞书机器人-指令)
  - [持仓管理](#持仓管理)
  - [组合管理](#组合管理)
  - [系统指令](#系统指令)
- [附录](#附录)
  - [通用错误码](#通用错误码)
  - [v1 路由说明](#v1-路由说明)

---

## 主服务 API（端口 8000）

### 1. 健康检查

检测主服务是否正常运行。

- **HTTP 方法**：`GET`
- **路径**：`/health`

#### 请求参数

无。

#### 返回格式

```json
{
  "status": "ok",
  "service": "mingce-main",
  "timestamp": 1710000000.123
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | 服务状态，`"ok"` 表示正常 |
| service | string | 服务名称标识 |
| timestamp | float | Unix 时间戳（秒） |

#### 示例

```bash
curl http://localhost:8000/health
```

#### 注意事项

- 无需认证。
- 可作为负载均衡或容器编排的健康检查探针。

---

### 2. 生成报告

异步触发报告生成任务。

- **HTTP 方法**：`POST`
- **路径**：`/api/report/generate`
- **查询参数**（Query String）：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| version | string | 是 | — | 报告版本：`close`（收盘）、`morning`（早盘）、`noon`（午盘）、`early`（开盘前） |

#### version 参数说明

| 取值 | 含义 | 典型时机 |
|------|------|----------|
| `close` | 收盘报告 | 每日 15:30 后 |
| `morning` | 早盘报告 | 每日 09:00 前 |
| `noon` | 午盘报告 | 每日 12:00 前后 |
| `early` | 盘前速览 | 每日 08:30 前 |

#### 返回格式

```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "pending",
  "message": "报告生成任务已提交"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| task_id | string | 任务唯一标识（UUID），用于后续查询任务状态 |
| status | string | 任务状态，初始为 `"pending"` |
| message | string | 提示信息 |

#### 示例

```bash
# 生成收盘报告
curl -X POST "http://localhost:8000/api/report/generate?version=close"

# 生成早盘报告
curl -X POST "http://localhost:8000/api/report/generate?version=morning"

# 生成午盘报告
curl -X POST "http://localhost:8000/api/report/generate?version=noon"

# 生成盘前速览
curl -X POST "http://localhost:8000/api/report/generate?version=early"
```

#### 注意事项

- 报告生成是**异步**的，返回的 `task_id` 用于轮询任务进度。
- `version` 参数必须为四个枚举值之一，否则返回 422 参数校验错误。
- 同一时间对同一 version 重复提交，可能会合并为同一个任务（取决于后端实现）。

---

### 3. 查询任务状态

查询异步任务的执行状态和结果。

- **HTTP 方法**：`GET`
- **路径**：`/api/task/{task_id}`

#### 请求参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| task_id | 路径参数 | string | 是 | 任务 UUID，由 `/api/report/generate` 返回 |

#### 返回格式

**任务进行中：**

```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "pending",
  "progress": 45,
  "message": "正在获取市场数据..."
}
```

**任务完成：**

```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "completed",
  "progress": 100,
  "result": {
    "report_url": "https://example.com/reports/20260616_close.html",
    "summary": "报告摘要文本..."
  }
}
```

**任务失败：**

```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "failed",
  "progress": 65,
  "error": "获取数据源超时"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| task_id | string | 任务唯一标识 |
| status | string | 状态枚举：`pending` / `running` / `completed` / `failed` |
| progress | int | 进度百分比（0-100） |
| message | string | 状态描述信息 |
| result | object | 任务完成时的结果数据（仅 completed 时有） |
| error | string | 错误信息（仅 failed 时有） |

#### 示例

```bash
curl http://localhost:8000/api/task/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

#### 注意事项

- `task_id` 不存在时返回 404。
- 建议客户端采用**指数退避**策略轮询（如 1s → 2s → 4s → 8s），避免频繁请求。
- 已完成的任务结果会缓存一段时间（TTL 由后端配置），过期后查询会返回 404。

---

### 4. 测试报告生成

同步测试报告生成流程，用于开发和调试。

- **HTTP 方法**：`POST`
- **路径**：`/api/report/test`

#### 请求参数

无。可选的请求体（JSON，仅测试环境使用）：

```json
{
  "mock_data": true,
  "version_override": "close"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| mock_data | boolean | 否 | 是否使用模拟数据（默认 `false`） |
| version_override | string | 否 | 强制指定报告版本（默认使用当前时段自动判断） |

#### 返回格式

```json
{
  "status": "success",
  "report": {
    "title": "2026-06-16 收盘报告（测试）",
    "sections": ["市场概况", "板块分析", "个股点评"],
    "generated_at": "2026-06-16T15:30:00+08:00"
  },
  "elapsed_ms": 1234
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | `"success"` 或 `"error"` |
| report | object | 测试生成的报告内容 |
| elapsed_ms | int | 生成耗时（毫秒） |

#### 示例

```bash
curl -X POST http://localhost:8000/api/report/test \
  -H "Content-Type: application/json" \
  -d '{"mock_data": true}'
```

#### 注意事项

- **仅限开发/测试环境使用**，生产环境应禁用此接口。
- 该接口为**同步**调用，大量数据时可能超时。
- 使用 `mock_data: true` 可在不依赖外部数据源的情况下验证报告生成逻辑。

---

### 5. 通用消息转发

将消息转发到指定的下游渠道（如飞书群、钉钉、企业微信等）。

- **HTTP 方法**：`POST`
- **路径**：`/api/send_message`

#### 请求参数

请求体（JSON）：

```json
{
  "channel": "feishu",
  "target": "group_xxx",
  "title": "消息标题",
  "content": "消息正文内容",
  "msg_type": "text"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| channel | string | 是 | 渠道标识：`feishu`（飞书）、`dingtalk`（钉钉）、`wecom`（企业微信） |
| target | string | 是 | 目标接收方标识（群 ID、Webhook URL 等） |
| title | string | 否 | 消息标题（部分渠道支持） |
| content | string | 是 | 消息正文 |
| msg_type | string | 否 | 消息类型：`text`（文本，默认）、`markdown`、`post`（富文本） |

#### 返回格式

```json
{
  "status": "sent",
  "message_id": "msg_xxxxxxxxxxxx",
  "channel": "feishu"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | `"sent"` 表示发送成功，其他值表示失败 |
| message_id | string | 渠道返回的消息 ID |
| channel | string | 实际使用的发送渠道 |

#### 示例

```bash
curl -X POST http://localhost:8000/api/send_message \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "feishu",
    "target": "oc_xxxxxxxxxxxxx",
    "title": "市场预警",
    "content": "今日市场出现异常波动，请注意风险。",
    "msg_type": "text"
  }'
```

#### 注意事项

- 发送失败时返回 HTTP 200 但 `status` 为 `"failed"`，需检查 `message_id` 字段。
- 各渠道支持的 `msg_type` 可能不同，建议优先使用 `text`。
- 请确保 `target` 对应的渠道已正确配置凭证。

---

### 6. 推送策略信号

接收外部策略系统推送的交易信号。

- **HTTP 方法**：`POST`
- **路径**：`/api/strategy-signals/push`

#### 请求参数

请求体（JSON）：

```json
{
  "strategy": "volatility_breakout",
  "symbol": "000001.SZ",
  "action": "buy",
  "price": 15.68,
  "volume": 10000,
  "confidence": 0.85,
  "timestamp": "2026-06-16T14:30:00+08:00",
  "metadata": {
    "reason": "突破20日波动率通道上轨",
    "indicators": {
      "volatility_ratio": 2.3,
      "volume_ratio": 1.8
    }
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| strategy | string | 是 | 策略名称标识 |
| symbol | string | 是 | 股票代码（含交易所后缀） |
| action | string | 是 | 操作：`buy`（买入）、`sell`（卖出）、`hold`（持有） |
| price | float | 是 | 信号产生时的价格 |
| volume | int | 否 | 建议交易量（股） |
| confidence | float | 否 | 信号置信度（0.0 - 1.0） |
| timestamp | string | 否 | 信号产生时间（ISO 8601 格式），默认当前时间 |
| metadata | object | 否 | 附加元数据，如策略理由、指标值等 |

#### 返回格式

```json
{
  "status": "accepted",
  "signal_id": "sig_xxxxxxxxxxxx",
  "inserted_at": "2026-06-16T14:30:05+08:00"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | `"accepted"` 表示接收成功 |
| signal_id | string | 信号唯一标识 |
| inserted_at | string | 服务端接收时间（ISO 8601） |

#### 示例

```bash
curl -X POST http://localhost:8000/api/strategy-signals/push \
  -H "Content-Type: application/json" \
  -d '{
    "strategy": "volatility_breakout",
    "symbol": "000001.SZ",
    "action": "buy",
    "price": 15.68,
    "volume": 10000,
    "confidence": 0.85,
    "metadata": {
      "reason": "突破20日波动率通道上轨"
    }
  }'
```

#### 注意事项

- 信号被接受后进入异步处理队列，不保证立即执行。
- `symbol` 建议使用带交易所后缀的完整代码格式（如 `.SZ`、`.SH`）。
- 大量高频推送时建议使用批量接口（如有）或控制推送频率。

---

## 信号服务 API（端口 8765）

### 1. 信号服务健康检查

检测信号分析服务是否正常运行。

- **HTTP 方法**：`GET`
- **路径**：`/health`

#### 请求参数

无。

#### 返回格式

```json
{
  "status": "ok",
  "service": "mingce-signal",
  "uptime_seconds": 3600,
  "version": "1.0.0"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | 服务状态 |
| service | string | 服务名称标识 |
| uptime_seconds | int | 服务已运行时长（秒） |
| version | string | 服务版本号 |

#### 示例

```bash
curl http://localhost:8765/health
```

#### 注意事项

- 无需认证。
- 主服务和信号服务的健康检查路径相同（`/health`），但端口不同。

---

### 2. 分析信号

提交数据供信号分析服务处理，返回分析结果。

- **HTTP 方法**：`POST`
- **路径**：`/analyze`

#### 请求参数

请求体（JSON）：

```json
{
  "symbols": ["000001.SZ", "600519.SH"],
  "start_date": "2026-06-01",
  "end_date": "2026-06-16",
  "indicators": ["ma", "rsi", "macd"],
  "strategy_params": {
    "ma_short": 5,
    "ma_long": 20,
    "rsi_period": 14
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbols | array[string] | 是 | 待分析的股票代码列表 |
| start_date | string | 是 | 分析数据起始日期（`YYYY-MM-DD`） |
| end_date | string | 是 | 分析数据截止日期（`YYYY-MM-DD`） |
| indicators | array[string] | 否 | 需要计算的指标列表：`ma`（均线）、`rsi`（相对强弱）、`macd`、`boll`（布林带）等 |
| strategy_params | object | 否 | 策略参数覆盖，不传则使用默认参数 |

#### 返回格式

```json
{
  "status": "success",
  "analysis_id": "anl_xxxxxxxxxxxx",
  "results": {
    "000001.SZ": {
      "signals": [
        {
          "date": "2026-06-16",
          "indicator": "ma",
          "action": "buy",
          "value": 15.60,
          "reason": "5日均线上穿20日均线"
        }
      ],
      "summary": {
        "total_signals": 3,
        "buy": 2,
        "sell": 1
      }
    },
    "600519.SH": {
      "signals": [],
      "summary": {
        "total_signals": 0,
        "buy": 0,
        "sell": 0
      }
    }
  },
  "elapsed_ms": 2345
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | `"success"` 或 `"error"` |
| analysis_id | string | 分析任务唯一标识 |
| results | object | 分析结果，key 为股票代码 |
| elapsed_ms | int | 分析耗时（毫秒） |

每个股票的结果包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| signals | array | 信号列表，每个信号包含日期、指标、操作、数值和原因 |
| summary | object | 信号汇总统计 |

#### 示例

```bash
curl -X POST http://localhost:8765/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "symbols": ["000001.SZ"],
    "start_date": "2026-06-01",
    "end_date": "2026-06-16",
    "indicators": ["ma", "rsi"]
  }'
```

#### 注意事项

- `start_date` 和 `end_date` 区间建议不超过 180 天，避免分析耗时过长。
- 股票代码必须包含交易所后缀，否则可能被拒绝。
- 分析可能较为耗时，建议客户端设置合理的超时时间（如 60 秒）。

---

## 飞书机器人 @指令

在飞书群中 @机器人 后可发送以下指令与系统交互。

### 持仓管理

#### 关注持仓

```
@机器人 关注
```

- **功能**：将当前用户标记为持仓关注者，开始接收持仓相关的推送通知。
- **返回**：机器人回复操作结果。

#### 取消关注持仓

```
@机器人 取消关注
```

- **功能**：取消持仓关注，停止接收持仓推送。
- **返回**：机器人回复操作结果。

### 组合管理

#### 查看/创建组合

```
@机器人 我的组合
```

- **功能**：查询当前用户的组合信息。如尚未创建组合，则引导用户创建。
- **返回**：组合名称、持仓列表、收益概况等。

#### 添加持仓

```
@机器人 持仓
```

- **功能**：为当前组合添加股票持仓。通常在交互式对话框中完成股票代码、数量、成本价的输入。
- **返回**：操作结果及更新后的持仓摘要。

#### 移除持仓

```
@机器人 移除持仓
```

- **功能**：从当前组合中移除指定持仓。通常在交互式对话框中完成选择。
- **返回**：操作结果及更新后的持仓摘要。

### 信号指令

```
@机器人 信号
```

- **功能**：查询最新的策略信号列表，包括信号来源、股票、操作建议等。
- **返回**：信号概览列表，包含策略名称、股票代码、操作类型和产生时间。

### 系统指令

```
@机器人 帮助
```

- **功能**：显示机器人可用指令列表及简要说明。
- **返回**：帮助菜单，列出所有支持的 @指令 及其功能描述。

#### 指令汇总

| 指令 | 功能 | 权限 |
|------|------|------|
| `关注` | 关注持仓推送 | 所有用户 |
| `取消关注` | 取消持仓推送 | 已关注用户 |
| `我的组合` | 查询/创建组合 | 所有用户 |
| `持仓` | 添加持仓 | 已创建组合的用户 |
| `移除持仓` | 移除持仓 | 已创建组合的用户 |
| `信号` | 查询策略信号 | 所有用户 |
| `帮助` | 显示帮助菜单 | 所有用户 |

#### 注意事项

- 所有指令均需在群聊中 **@机器人** 触发。
- 某些指令（如 `持仓`、`移除持仓`）会触发交互式卡片对话框，请按引导完成操作。
- 指令执行结果将以飞书消息或卡片形式返回。
- 指令支持中文全角/半角符号，但建议使用纯文本。

---

## 附录

### 通用错误码

| HTTP 状态码 | 说明 | 常见原因 |
|-------------|------|----------|
| 200 | 请求成功 | — |
| 400 | 请求参数错误 | 缺少必填字段、参数格式错误 |
| 404 | 资源不存在 | task_id 无效、路径错误 |
| 422 | 参数校验失败 | 枚举值不合法、字段类型错误 |
| 429 | 请求频率超限 | 短时间内请求过多 |
| 500 | 服务器内部错误 | 后端异常、数据源不可用 |
| 502 | 上游服务不可用 | 依赖的外部 API 或数据库故障 |
| 503 | 服务暂时不可用 | 服务正在重启或过载 |

### v1 路由说明

主服务部分 API 在 `/api/v1/` 路径下也提供兼容版本：

| 新版路径 | v1 兼容路径 |
|----------|-------------|
| `POST /api/report/generate` | `POST /api/v1/report/generate` |
| `GET /api/task/{task_id}` | `GET /api/v1/task/{task_id}` |
| `POST /api/report/test` | `POST /api/v1/report/test` |
| `POST /api/send_message` | `POST /api/v1/send_message` |
| `POST /api/strategy-signals/push` | `POST /api/v1/strategy-signals/push` |

> **建议**：新开发请使用不带 `/v1` 的最新路径。v1 路由仅为向后兼容保留，未来版本可能移除。

---

> 文档版本：v1.0.0 | 最后更新：2026-06-16
