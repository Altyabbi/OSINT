# 军事开源情报（OSINT）分析系统 — 一期

以 WarSpotting（warspotting.net）公开战损数据 API 为核心数据源的俄军装备战损分析系统。
架构为 **"workflow 为骨架、agent 为交互层"**：采集、统计、日报生成走确定性流水线；
问答功能采用 LLM 工具调用模式（未配置 LLM key 时自动降级为关键词路由，见下文）。

> 口径声明：本系统数据为 **目视确认损失**，实际损失高于统计数字。
> 所有内容基于开源数据、仅供参考。数据来源署名：WarSpotting。

## 目录结构

```
military-osint/
├── ingestion/       # WarSpotting 采集（client/parse/pipeline）+ APScheduler 调度
├── storage/         # SQLAlchemy 表结构（loss_events / ingestion_logs）与建表
├── analytics/       # 统计计算（纯代码）：聚合、日/周/月趋势、地理分布、基线异常
├── pipelines/       # 日报 workflow（节点化）、LLM client 抽象、fallback writer
├── agent/           # 问答 agent（LLM 工具调用）+ 语义化工具集 + 降级路由
├── outputs/         # matplotlib 图表、folium 热力图渲染
├── evals/           # 数字一致性校验（报告数字与数据库统计对账，不符即拦截）
├── dashboard/       # Streamlit 多页面 Web 应用（概览/查询/采集/日报/问答/系统信息）
├── tests/           # 单元测试（SQLite + 假数据，不打外网）
├── docs/schema.md   # 数据库表结构说明
├── docker-compose.yml  # PostgreSQL + PostGIS 一键启动
├── run.py           # CLI 入口
└── config.py        # pydantic-settings 全局配置
```

## 一、环境配置

```bash
# Python 3.10+（开发环境为 conda 环境 nli，Python 3.10.19）
pip install -r requirements.txt
cp .env.example .env   # 按需修改；不改也能跑（默认 SQLite、无 LLM）
```

配置项（全部走环境变量 / `.env`，见 `config.py`）：

- `DATABASE_URL`：默认 `sqlite:///data/osint.db`；生产切
  `postgresql+psycopg2://osint:osint@localhost:5432/osint`
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`：LLM（OpenAI 兼容）。
  **不配置时**：日报解读自动使用确定性 fallback writer（日志标注 `撰写方式=fallback`），
  问答降级为关键词路由。**报告中所有数字始终由代码计算，LLM/fallback 只写文字解读。**
- `REQUEST_INTERVAL_SECONDS`（默认 1.5s，礼貌抓取限速）、`MAX_RETRIES` 等采集参数

数据库（可选，有 Docker 权限的环境）：

```bash
docker compose up -d   # 拉起 PostgreSQL 16 + PostGIS 3.4，并自动启用 postgis 扩展
# 然后把 .env 的 DATABASE_URL 改为 postgresql+psycopg2://osint:osint@localhost:5432/osint
```

坐标存储采用 Float 经纬度列 + haversine 半径查询，SQLite/PostgreSQL 行为一致，
PostGIS 仅为后续升级预留（详见 `docs/schema.md`）。

## 二、首次全量采集（全量回溯）

```bash
python run.py ingest --backfill
```

从 2022-02-24 回溯至昨日。**预估耗时**：约 1600+ 天 ×（限速 1.5s + 请求耗时）
≈ **2.5~4 小时**（不含偶发重试）。单日失败不中断整体任务，失败明细写入采集日志表；
可随时 Ctrl-C 中断后用 `ingest --from <中断日> --to <昨日>` 续采（幂等，无脏数据）。

区间采集 / 补采最近 N 天：

```bash
python run.py ingest --from 2026-09-22 --to 2026-10-05
python run.py ingest --backfill-recent 3
```

每次按日采集的原始 JSON 快照存档于 `data/raw/YYYY-MM-DD.json`；
采集任务的范围、新增/更新数、成败状态记录在 `ingestion_logs` 表。

## 三、日常运行（每日增量）

方式 A — 内置 APScheduler：

```bash
python -m ingestion.scheduler   # 每天 06:40（可配）采集最近 3 天，覆盖迟到数据
```

方式 B — 系统 cron：

```cron
40 6 * * * cd /path/to/military-osint && python run.py ingest --backfill-recent 3
```

## 四、日报手动触发

```bash
python run.py report --date 2024-06-15   # 不指定日期则默认昨日
```

产出到 `outputs/reports/`：

- `daily_report_YYYY-MM-DD.md` — Markdown 日报（当日统计、近 7/30 日均值对比异常点、
  地理分布、重点型号、解读文字，含口径声明/快照时间/来源署名/记录 ID）
- `daily_YYYY-MM-DD_by_type.png` / `_by_status.png` / `_trend30d.png` — matplotlib 图表
- `daily_YYYY-MM-DD_heatmap.html` — folium 热力图

日报 workflow 节点：`collect → render_charts → render_map → write → assemble → verify`。
`verify` 节点把报告全文中出现的每个数字与代码计算的统计结果对账，
**对不上即拦截（抛 NumberMismatchError），不允许输出**；LLM 撰写的解读若未通过
对账会自动降级为 fallback 模板并重写（日志有记录）。

## 五、数据问答（agent）

```bash
python run.py ask "2024-06-15 俄军损失了多少辆坦克？"
python run.py ask "近7天装甲损失趋势？"
python run.py ask "单位\"第114旅\"的损失历史？"
```

- 配置了 `OPENAI_API_KEY`：LLM 工具调用模式，只开放 4 个语义化工具函数
  （`query_losses` / `compare_periods` / `get_trend` / `get_unit_history`），
  **不开放任意 SQL**；每个工具返回结构化数据（含记录 ID 来源），LLM 负责组织语言。
- 未配置 key：降级为确定性关键词路由（识别日期/近 N 天/上周/上月、类别关键词、
  型号正则、单位引号），调用同一组工具函数组装回答；无法识别的意图会给出明确提示。
  降级模式的"今天"以库内最新数据日期为参照。
- 两条路径的回答数字都会经过 `evals/number_check` 对账，不符即拦截报错。

## 六、Web 交互界面（Streamlit）

```bash
conda run -n nli streamlit run dashboard/app.py
# 或：python run.py dashboard
```

侧边栏导航共 6 个页面，覆盖系统全部功能：

- **概览 Dashboard**：核心指标卡（总记录数、数据日期范围、有坐标记录数、最近采集时间）、
  近 30 天趋势图、近 90 天 folium 热力图。
- **数据查询**：时间段/类别/型号/状态/地名多维筛选，明细表格 + CSV 导出，
  按类别/状态聚合图与型号 TOP 10。
- **数据采集**：页面内选择日期区间或"近 N 天"触发采集（单次上限 30 天，st.spinner 同步执行，
  限速下单天约 2 秒），展示拉取/新增/更新/失败天数结果与最近 20 条采集日志；
  全量回溯仍走命令行 `python run.py ingest --backfill`。
- **日报中心**：选择日期触发生成日报（完整流水线 + 数字校验，失败会明确报错），
  渲染 Markdown 正文、图表 PNG、内嵌 folium 热力图；可下拉浏览 `outputs/reports/` 历史报告。
- **智能问答**：聊天式界面（保留对话历史），调用 agent 模块（无 LLM key 走降级路由），
  展示回答 + 命中的结构化数据表格 + 引用的记录 ID。
- **系统信息**：当前配置（数据库类型、LLM 是否配置、API 地址等）、数字可信机制说明、
  口径声明与 WarSpotting 署名。

实现说明：`dashboard/common.py` 用 `st.cache_resource` 管理 engine/session 工厂、
`st.cache_data`（30s TTL）缓存慢变选项；采集/生成报告后调用 `refresh_caches()` 清缓存刷新。
页面模块拆分为 `dashboard/page_*.py`，后端调用（`run_ingestion` / `run_report` / `run_agent`）
与 CLI 完全共用同一套 pipeline/agent 代码。各页面后端可用脚本一键冒烟验证：

```bash
conda run -n nli python scripts/verify_web_backend.py   # 查询/采集/日报/问答后端实跑
conda run -n nli python scripts/verify_web_pages.py     # AppTest 无头逐页渲染，检查异常
```

## 七、测试

```bash
python -m pytest tests/ -q
```

覆盖：API 记录解析（geo 解析、字段容错）、幂等 upsert 与状态流转追踪、
统计聚合/趋势/haversine 半径查询/基线异常、数字一致性校验、
日报流水线端到端（fallback 撰写 + 文件产出）、agent 降级问答。

## 八、设计要点与已知取舍

- **数字可信**：报告/回答中的所有数字由代码计算（`analytics` 纯代码层），
  `evals` 对账拦截任何不在统计结果中的数字（防 LLM 幻觉）。
- **幂等采集**：以 WarSpotting 记录 ID 为主键 upsert；重复采集新增/更新均为 0；
  状态流转（如 Abandoned→Captured）追加到 `status_history`。
- **限速与重试**：默认 1.5s 间隔；5xx/429/网络错误指数退避重试 5 次；
  单日失败不中断任务，写入采集日志。
- **Python 版本**：开发环境实测为 3.10（需求写 3.11+），代码兼容 3.10+，
  未使用 3.11 独有语法。
- **二期预留**：图像识别、新闻流接入不做；photos/sources/comment 字段已在模型中预留。
