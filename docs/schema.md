# 数据库表结构说明

ORM 定义见 `storage/models.py`（SQLAlchemy 2.0）。默认数据库为 SQLite（`data/osint.db`），
生产环境通过 `DATABASE_URL` 切换到 PostgreSQL + PostGIS（`docker compose up -d` 一键启动，
PostGIS 扩展由 `docker/initdb/01_postgis.sql` 自动启用）。

> 坐标设计说明：为保证 SQLite/PostgreSQL 两库通用，坐标用 `latitude`/`longitude`
> 两个 Float 列（均带索引）存储，半径查询先用经纬度窗口粗筛、再用 haversine 公式
> 精算（`analytics/stats.py: losses_in_radius`）。迁移到 PostgreSQL 后可平滑升级为
> PostGIS `geography` 类型 + `ST_DWithin`，应用层接口不变。

## 1. loss_events — 战损事件表

主键即 WarSpotting 原始记录 ID（幂等 upsert 的锚点，重复采集不产生脏数据）。

| 列 | 类型 | 说明 |
| --- | --- | --- |
| id | INTEGER / BIGINT | 主键，WarSpotting 记录原始 ID |
| date | DATE | 损失日期（索引） |
| type | VARCHAR(128) | 装备类别，如 Tanks / Drones / Artillery（索引） |
| model | VARCHAR(256) NULL | 具体型号，如 T-72B3（索引） |
| status | VARCHAR(32) | Destroyed / Damaged / Abandoned / Captured（索引） |
| lost_by | VARCHAR(32) NULL | 损失方（当前采集 Russia） |
| nearest_location | VARCHAR(256) NULL | 最近地点（索引，用于地名区域过滤） |
| latitude | FLOAT NULL | 纬度（索引；API geo 字段解析而来） |
| longitude | FLOAT NULL | 经度（索引） |
| unit | VARCHAR(256) NULL | 所属部队/单位（索引） |
| tags | TEXT NULL | 标签（逗号分隔原文） |
| comment | TEXT NULL | 备注（当前 API 未返回，预留） |
| sources | TEXT NULL | 来源链接，JSON 数组文本（当前 API 未返回，预留） |
| photos | TEXT NULL | 照片链接，JSON 数组文本（当前 API 未返回，预留） |
| raw_json | TEXT | 原始 API 记录 JSON 整体存档 |
| status_history | TEXT | 状态流转历史 JSON 数组，如 `[{"from":"Abandoned","to":"Captured","at":"..."}]` |
| first_seen_at | TIMESTAMP TZ | 首次采集到该记录的时间 |
| last_seen_at | TIMESTAMP TZ | 最近一次该记录发生更新的时间 |

复合索引：`(date, type)`、`(date, status)`。

### 状态流转追踪

重复采集时若记录字段发生变化（典型如 `Abandoned → Captured`），更新字段值、
向 `status_history` 追加流转条目，并在采集日志中计入 `records_updated`。

## 2. ingestion_logs — 采集日志表

| 列 | 类型 | 说明 |
| --- | --- | --- |
| id | INTEGER | 主键，自增 |
| started_at | TIMESTAMP TZ | 任务开始时间 |
| finished_at | TIMESTAMP TZ NULL | 任务结束时间 |
| date_from / date_to | DATE | 采集的日期区间（闭区间） |
| records_fetched | INTEGER | API 拉取到的记录总数 |
| records_new | INTEGER | 新增入库记录数 |
| records_updated | INTEGER | 字段发生变化的更新记录数 |
| days_ok / days_failed | INTEGER | 成功/失败天数（单日失败不中断整体任务） |
| status | VARCHAR(16) | running / success / partial / failed |
| error | TEXT NULL | 失败明细（逐日一行） |

## 3. 磁盘 raw 快照

每次按日采集的原始 API 响应另存一份到 `data/raw/YYYY-MM-DD.json`
（含 `fetched_at`、`date`、`losses` 数组），作为数据库之外的原始证据留档。
