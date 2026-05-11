# 投资持仓追踪

个人投资组合管理 Web 应用，支持 A 股、美股、日股多市场持仓记录，自动抓取行情，以人民币汇总总资产。

## 功能

- **多市场支持** — A 股（沪深）、美股、日股、加密货币
- **自动行情** — A 股通过 [Tushare Pro](https://tushare.pro) 获取，美股/日股/加密通过 yfinance 获取
- **汇率换算** — 自动获取 USD/JPY 对 CNY 汇率，所有持仓以人民币汇总
- **手动价格** — 可为任意标的手动设置价格，屏蔽自动抓取
- **标签分类** — 为持仓添加自定义标签，支持按标签筛选
- **交易记录** — 记录每笔买卖交易，自动重算持仓成本和数量
- **趋势分析** — 资产组合历史净值曲线、各持仓/标签历史市值走势图
- **可视化** — 资产分配饼图 + 持仓市值柱状图
- **Docker 部署** — Docker Compose 配置（Flask + MCP + PostgreSQL），通过外部 `edge_net` 网络接入用户自管的反向代理

## 快速开始

### 前置条件

- [Docker](https://docs.docker.com/get-docker/) 及 Docker Compose
- [Tushare Pro](https://tushare.pro) 账号（用于 A 股行情，免费注册）

### 部署步骤

**1. 克隆仓库**

```bash
git clone https://github.com/your-username/personal-finance.git
cd personal-finance
```

**2. 配置环境变量**

```bash
cp .env.example .env
```

编辑 `.env`，填入以下必填项：

```ini
POSTGRES_PASSWORD=your_strong_password
SECRET_KEY=your_random_32char_secret
TUSHARE_TOKEN=your_tushare_token

# 可选：开启鉴权
ACCESS_TOKEN=your_web_token
MCP_TOKEN=your_mcp_token

# 可选：Cloudflare Tunnel
TUNNEL_TOKEN=your_cloudflare_tunnel_token
```

**3. 创建外部网络（首次部署）**

`docker-compose.yml` 声明了 `edge_net` 为 external network，用于让反向代理（自建 nginx、Cloudflare Tunnel 等）通过 Docker DNS 别名访问 `personal-finance-web` 和 `personal-finance-mcp`：

```bash
docker network create edge_net
```

**4. 启动**

```bash
docker compose up -d --build
```

**5. 访问**

服务默认仅监听 Docker 内部网络（容器内 `web:5000`、`mcp:8000`），通过你自己的反向代理对外暴露。本地调试可临时在 `docker-compose.yml` 给 web/mcp 加 `ports` 映射。

---

### 本地开发（不使用 Docker）

```bash
pip install -r requirements.txt

# 使用 SQLite，无需 PostgreSQL
export TUSHARE_TOKEN=your_tushare_token_here   # A 股行情需要
python app.py
```

访问 `http://localhost:5000`。

## 标的代码格式

| 市场 | 格式 | 示例 |
|------|------|------|
| A 股（沪） | `代码.SH` | `600519.SH` |
| A 股（深） | `代码.SZ` | `000001.SZ` |
| 美股 | ticker | `AAPL` |
| 日股 | `代码.T` | `7203.T` |
| 加密货币 | `代码-USD` | `BTC-USD` |

## 架构

```
外部反向代理（用户自管，e.g. nginx + Cloudflare Tunnel）
  │
  └─ edge_net (Docker external network)
       ├─ personal-finance-web :5000  →  Flask + Gunicorn  ┐
       └─ personal-finance-mcp :8000  →  MCP HTTP server   ├─→  PostgreSQL (db:5432)
                                                            ┘
```

| 容器 | 镜像 | 说明 |
|------|------|------|
| `web` | 本地构建 | Flask + Gunicorn，2 workers，端口 5000 |
| `mcp` | 本地构建 | MCP streamable-http 服务，端口 8000，Bearer Token 鉴权 |
| `db` | postgres:16-alpine | 数据持久化，仅监听 127.0.0.1:5432 |

`web` 和 `mcp` 都同时接入 `default` 网络（互相 + db 通信）和 `edge_net` 外部网络（暴露给反向代理）。

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `POSTGRES_PASSWORD` | 是 | — | PostgreSQL 密码 |
| `SECRET_KEY` | 是 | — | Flask Session 密钥 |
| `TUSHARE_TOKEN` | 否 | — | A 股行情 Token，不填则 A 股无法自动刷新 |
| `ACCESS_TOKEN` | 否 | — | Web 全站鉴权 Token，设置后强制登录，留空则关闭鉴权 |
| `MCP_TOKEN` | 否 | — | MCP HTTP 端点 Bearer Token，设置后强制鉴权，留空则关闭 |
| `POSTGRES_DB` | 否 | `portfolio` | 数据库名 |
| `POSTGRES_USER` | 否 | `portfolio` | 数据库用户名 |
| `MCP_HOST` | 否 | `0.0.0.0` | MCP 服务绑定地址 |

## 访问鉴权

在 `.env` 中设置 `ACCESS_TOKEN` 即可开启全站鉴权：

```ini
ACCESS_TOKEN=your_strong_token_here
```

设置后重新构建生效：

```bash
docker compose up -d --build web
```

### 网页访问

浏览器打开应用时会自动跳转到登录页，输入 `ACCESS_TOKEN` 的值即可登录。登录后 navbar 右上角有"退出"按钮。

### API / MCP 访问

外部脚本或 OpenClaw 等 Agent 调用 REST API 时，在请求头中携带 Bearer Token：

```
Authorization: Bearer your_strong_token_here
```

示例（假设你的反向代理把外部域名 `your-domain` 转发到 `personal-finance-web:5000` / `personal-finance-mcp:8000`）：

```bash
# REST API
curl -X POST https://your-domain/api/refresh-prices \
  -H "Authorization: Bearer your_strong_token_here"

# MCP 端点（需同时声明两种 Accept）
curl -s https://your-domain/mcp \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer your_mcp_token" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'
```

MCP Server（stdio 模式）直连数据库，不经过 HTTP，无需 Token。HTTP 模式下使用 `MCP_TOKEN` 独立鉴权，见下方 MCP Server 章节。

---

## 常用命令

```bash
# 查看日志
docker compose logs -f web

# 重新构建并更新应用
docker compose up -d --build web

# 备份数据库
docker compose exec db pg_dump -U portfolio portfolio > backup_$(date +%Y%m%d).sql

# 恢复数据库
docker compose exec -T db psql -U portfolio portfolio < backup.sql

# 停止所有服务
docker compose down
```

## 数据库迁移说明

全新部署无需手动操作，`init_db()` 启动时自动建表。

从旧版本升级时，如缺少以下字段，需手动执行对应 SQL：

```sql
-- 标签字段（旧版升级）
ALTER TABLE holdings ADD COLUMN tags VARCHAR(200) DEFAULT '';
```

交易记录表（`transactions`）和历史净值表（`portfolio_value_history`、`price_history`）由 `init_db()` 自动创建。

历史净值快照通过 `/api/backfill-value-history` 接口或每日价格刷新时自动写入。

## API

应用提供 JSON API 供外部脚本或二次开发使用，详见 [API.md](API.md)。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/holdings/search` | GET | 按名称/代码模糊查询持仓 |
| `/api/holdings` | GET / POST | 列出全部持仓 / 新增持仓 |
| `/api/holdings/<id>` | GET / PATCH | 查看持仓详情 / 修改 name/notes/tags |
| `/api/holdings/<id>/quantity` | PATCH | 修改持仓份数（绝对值或增量） |
| `/api/holdings/<id>/tags` | PATCH | 修改持仓标签 |
| `/api/holdings/<id>/transactions` | POST | 新增交易记录（可联动对方持仓） |
| `/api/transactions` | GET | 列出交易（可按 `?holding_id=` 过滤） |
| `/api/transactions/<id>` | PATCH / DELETE | 修改 / 删除交易（联动重算持仓） |
| `/api/portfolio` | GET | 组合汇总（总市值/盈亏/今日变化） |
| `/api/portfolio-data` | GET | 饼图数据 |
| `/api/tags` | GET | 标签维度市值汇总 |
| `/api/exchange-rates` | GET | 当前缓存汇率 |
| `/api/refresh-prices` | POST | 刷新所有持仓行情 + 汇率 |
| `/api/override-price` | POST | 手动设置价格 |
| `/api/clear-override` | POST | 清除手动价格 |
| `/api/price-history/<symbol>` | GET | 获取某标的历史价格 |
| `/api/portfolio-value-history` | GET | 获取组合历史净值（每日快照） |
| `/api/holding-value-history/<symbol>` | GET | 获取某持仓历史市值 |
| `/api/tag-value-history/<tag>` | GET | 获取某标签下历史市值 |
| `/api/backfill-value-history` | POST | 补全历史净值快照 |

## MCP Server（AI 集成）

通过 [Model Context Protocol (MCP)](https://modelcontextprotocol.io) 将持仓数据和操作暴露给 AI 助手，无需打开浏览器即可让 AI 直接查询、分析和修改投资组合。

支持两种传输模式：
- **stdio** — 本地进程模式，供 Claude Code / Claude Desktop 使用，无需鉴权
- **streamable-http** — HTTP 服务模式，供远程 Agent（如 OpenClaw、mcporter）通过网络访问，支持 Bearer Token 鉴权

### 安装依赖

```bash
pip install "mcp[cli]>=1.26.0"
```

### 模式一：本地 stdio（Claude Code / Claude Desktop）

```bash
# SQLite（本地开发）
DATABASE_URL=sqlite:///portfolio.db python mcp_server.py

# PostgreSQL
DATABASE_URL=postgresql://portfolio:PASSWORD@localhost:5432/portfolio python mcp_server.py
```

**配置 Claude Code** — 项目根目录已包含 `.mcp.json`，在此目录打开 Claude Code 后会自动加载。如需修改：

```json
{
  "mcpServers": {
    "portfolio-tracker": {
      "command": "python",
      "args": ["/root/personal-finance/mcp_server.py"],
      "env": {
        "DATABASE_URL": "sqlite:////root/personal-finance/portfolio.db"
      }
    }
  }
}
```

**配置 Claude Desktop** — 编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）或 `%APPDATA%\Claude\claude_desktop_config.json`（Windows），添加同样的 `mcpServers` 配置。

### 模式二：HTTP 远程访问（跨服务器 Agent）

在服务器上以 `streamable-http` 模式启动：

```bash
TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8000 \
  DATABASE_URL=postgresql://portfolio:PASSWORD@localhost:5432/portfolio \
  python mcp_server.py
```

MCP 端点地址（容器内/外部反向代理后端）：`http://personal-finance-mcp:8000/mcp` 或 `http://<服务器IP>:8000/mcp`

**Docker Compose 一键启动**（推荐）：

```bash
docker network create edge_net   # 首次部署
docker compose up -d
```

`web`（端口 5000）和 `mcp`（端口 8000）会自动加入 `edge_net` 外部网络，方便用户自管的反向代理（自建 nginx、Cloudflare Tunnel 等）通过 Docker DNS 别名转发。常见路由约定：

| 路径 | 反向代理转发目标 |
|------|----------------|
| `/` | `http://personal-finance-web:5000` |
| `/api/...` | `http://personal-finance-web:5000` |
| `/mcp` | `http://personal-finance-mcp:8000` |

#### MCP HTTP 鉴权

在 `.env` 中设置 `MCP_TOKEN`，MCP 端点即开启 Bearer Token 鉴权：

```ini
MCP_TOKEN=your_strong_mcp_token
```

调用时需在请求头中携带（MCP 协议要求同时声明两种 Accept 格式）：

```
Authorization: Bearer your_strong_mcp_token
Accept: application/json, text/event-stream
```

**mcporter 配置示例**（token 从环境变量读取，不写入文件）：

```json
{
  "servers": {
    "portfolio-tracker": {
      "url": "https://<你的域名>/mcp",
      "headers": {
        "Authorization": "Bearer ${MCP_TOKEN}"
      }
    }
  }
}
```

在 shell 中 `export MCP_TOKEN=your_token`，mcporter 会自动替换 `${MCP_TOKEN}`。

#### 通过 Cloudflare Tunnel 暴露（参考方案）

在 `edge_net` 上另起 cloudflared 容器，连接同一外部网络后即可在 Cloudflare 控制台把 Public Hostname 指向 `http://personal-finance-mcp:8000` 或 `http://personal-finance-web:5000`。示例 compose（独立于本仓库）：

```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel --no-autoupdate run
    environment:
      TUNNEL_TOKEN: your_cloudflare_tunnel_token
    networks: [edge_net]
networks:
  edge_net:
    external: true
```

### 可用 Tools

**读工具**

| Tool | 说明 |
|------|------|
| `get_portfolio_summary` | 完整持仓汇总（总市值/成本/盈亏 + 各持仓明细） |
| `get_holding_detail` | 单个持仓详情：当前价/盈亏/标签 + 全部交易 + 近 60 天价格 |
| `search_holdings` | 按名称或代码搜索持仓，空字符串返回全部 |
| `list_transactions` | 查看某持仓的全部交易记录 |
| `get_tags` | 各标签的市值合计与占比 |
| `get_exchange_rates` | 当前缓存汇率（USD/JPY/HKD 等对 CNY） |
| `get_price_history` | 某标的的全部历史价格 |
| `get_portfolio_value_history` | 组合每日净值时间序列 |
| `get_holding_value_history` | 单个持仓的每日市值时间序列 |
| `get_tag_value_history` | 单个标签下的每日市值时间序列 |

**写工具**

| Tool | 说明 |
|------|------|
| `add_holding` | 新增持仓 |
| `update_holding` | 修改持仓的 name/notes/tags |
| `update_holding_quantity` | 更新持仓数量（绝对值或增量） |
| `update_holding_tags` | 替换持仓标签列表 |
| `delete_holding` | 删除持仓（需传 `confirm=true`） |
| `add_transaction` | 记录买卖/转入转出，自动重算持仓成本和数量，可联动对方持仓 |
| `update_transaction` | 修改交易字段，重算所属持仓 |
| `delete_transaction` | 删除交易（联动删除配对交易，需传 `confirm=true`） |
| `refresh_prices` | 从 Tushare/eastmoney/yfinance/ICBC 刷新行情和汇率 |
| `set_price_override` | 手动设置某标的价格 |
| `clear_price_override` | 清除手动价格，恢复自动抓取 |
| `backfill_history` | 按历史价格回填组合/持仓/标签每日净值快照 |

### 示例对话

加载 MCP Server 后，可以直接用自然语言操作：

```
"帮我查看当前持仓组合，哪些持仓亏损超过 10%？"
"把 AAPL 的持仓数量增加 10 股"
"为我的所有 A 股持仓打上 '长期持有' 标签"
"刷新所有行情，然后告诉我今日盈亏"
```

---

## License

Copyright (c) 2026 watashihame. Released under the [MIT License](LICENSE).
