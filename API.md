# API 说明文档

本应用提供一组 JSON API 端点，用于价格管理和图表数据获取，可供前端页面或外部脚本调用。

**Base URL：** `http://<host>/api`

---

## 目录

- [刷新行情价格](#1-刷新行情价格)
- [手动设置价格](#2-手动设置价格)
- [清除手动价格](#3-清除手动价格)
- [获取图表数据](#4-获取图表数据)

---

## 枚举值说明

| 字段 | 可选值 |
|------|--------|
| `market` | `CN` `US` `JP` `CRYPTO` `OTHER` |
| `asset_type` | `stock` `etf` `fund` `bond` `crypto` `other` |
| `currency` | `CNY` `USD` `JPY` `HKD` `EUR` `GBP` |

## 标签（tags）字段说明

`tags` 字段存储于 `holdings` 表，为逗号分隔的字符串，在 API 响应中以字符串数组形式返回。

- 存储格式（数据库）：`"科技,长期持有,核心仓位"`
- API / 模板中：`["科技", "长期持有", "核心仓位"]`
- 单个标签不含逗号，长度不限，区分大小写
- 持仓列表页支持按标签筛选：`GET /holdings?tag=科技`

**Symbol 格式：**

| 市场 | 格式示例 | 数据来源 |
|------|----------|----------|
| A 股（沪） | `600519.SH` | Tushare Pro |
| A 股（深） | `000001.SZ` | Tushare Pro |
| 美股 | `AAPL` | yfinance |
| 日股 | `7203.T` | yfinance |
| 加密货币 | `BTC-USD` | yfinance |

---

## 1. 刷新行情价格

触发所有持仓的行情抓取，同时更新汇率缓存。标记为"手动价格"的持仓不会被覆盖。

```
POST /api/refresh-prices
```

**请求体：** 无

**响应示例（成功）：**

```json
{
  "updated": 5,
  "failed": 1,
  "errors": ["BTC-USD: 获取失败"],
  "timestamp": "2026-03-29 08:30 UTC"
}
```

**响应字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `updated` | integer | 成功更新的标的数量 |
| `failed` | integer | 获取失败的标的数量 |
| `errors` | string[] | 各失败条目的错误描述 |
| `timestamp` | string | 本次刷新完成时间（UTC） |

**响应示例（持仓为空）：**

```json
{
  "updated": 0,
  "failed": 0,
  "errors": [],
  "timestamp": ""
}
```

---

## 2. 手动设置价格

为指定标的设置一个手动价格。设置后，该标的将跳过自动行情抓取，直到调用"清除手动价格"接口。

```
POST /api/override-price
Content-Type: application/json
```

**请求体：**

```json
{
  "symbol": "600519.SH",
  "price": 1850.00,
  "currency": "CNY"
}
```

**请求字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `symbol` | string | 是 | 标的代码，不区分大小写，自动转大写 |
| `price` | number | 是 | 价格，必须大于 0 |
| `currency` | string | 否 | 货币，默认 `CNY` |

**响应示例（成功）：**

```json
{
  "ok": true,
  "symbol": "600519.SH",
  "price": 1850.0
}
```

**响应示例（失败）：**

```json
{
  "error": "无效的 symbol 或 price"
}
```

**HTTP 状态码：**

| 状态码 | 含义 |
|--------|------|
| 200 | 设置成功 |
| 400 | 参数错误（缺少字段、价格非正数等） |

---

## 3. 清除手动价格

取消指定标的的手动价格覆盖，恢复自动行情抓取。

```
POST /api/clear-override
Content-Type: application/json
```

**请求体：**

```json
{
  "symbol": "600519.SH"
}
```

**请求字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `symbol` | string | 是 | 标的代码 |

**响应示例（成功）：**

```json
{
  "ok": true,
  "symbol": "600519.SH"
}
```

**响应示例（失败）：**

```json
{
  "error": "缺少 symbol"
}
```

**HTTP 状态码：**

| 状态码 | 含义 |
|--------|------|
| 200 | 操作成功（即使该标的原本不是手动价格） |
| 400 | 缺少 symbol 字段 |

---

## 4. 获取图表数据

返回当前持仓的市值分布数据，按市值从高到低排序，供 Chart.js 饼图和柱状图使用。

```
GET /api/portfolio-data
```

**请求体：** 无

**响应示例：**

```json
{
  "labels": [
    "贵州茅台 (600519.SH)",
    "Apple Inc. (AAPL)",
    "Toyota (7203.T)"
  ],
  "values": [
    185000.00,
    45230.50,
    12800.00
  ],
  "colors": [
    "#4e79a7",
    "#f28e2b",
    "#e15759"
  ]
}
```

**响应字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `labels` | string[] | 持仓名称+代码，与 `values` 一一对应 |
| `values` | number[] | 各持仓市值（人民币，保留 2 位小数） |
| `colors` | string[] | 对应图表颜色（十六进制，循环使用固定色盘） |

> 标签数据不包含在此端点中。如需按标签过滤持仓，使用页面路由 `/holdings?tag=<标签名>`。

**说明：**
- 若某持仓无行情缓存，市值以成本价代替计算
- 所有金额已通过汇率转换为人民币（CNY）

---

## 错误格式

所有 API 错误均返回以下结构：

```json
{
  "error": "错误描述"
}
```

---

## 调用示例

**curl — 刷新价格：**
```bash
curl -X POST http://localhost/api/refresh-prices
```

**curl — 手动设置价格：**
```bash
curl -X POST http://localhost/api/override-price \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL", "price": 178.50, "currency": "USD"}'
```

**curl — 清除手动价格：**
```bash
curl -X POST http://localhost/api/clear-override \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL"}'
```

**curl — 获取图表数据：**
```bash
curl http://localhost/api/portfolio-data
```

**JavaScript fetch — 刷新价格：**
```javascript
const res = await fetch('/api/refresh-prices', { method: 'POST' });
const data = await res.json();
console.log(`更新 ${data.updated} 个，失败 ${data.failed} 个`);
```
