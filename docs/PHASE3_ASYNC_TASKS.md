# Phase 3：Celery 后台诊断与 SSE 断点续传

本里程碑把耗时诊断从 FastAPI 请求线程移到 Celery worker，同时保留 `inline` 模式，便于单元测试和不依赖 Redis 的本地开发。

## 两种运行模式

- `OPSPILOT_TASK_MODE=inline`：API 直接执行诊断。它是代码默认值，适合测试和最小化开发环境。
- `OPSPILOT_TASK_MODE=celery`：API 先写入 `QUEUED` 和 `task_queued` 轨迹、提交事务，再把任务 ID 投递到 Redis。Docker 示例默认使用此模式。

必须先提交数据库再投递任务，否则速度很快的 worker 可能先于事务提交查询事件，得到不存在的记录。若 Redis 投递失败，API 会把事件更新为 `FAILED`，追加 `task_dispatch_failed`，并返回 HTTP 503，而不是让任务静默丢失。

## Worker 生命周期

worker 命令为：

```bash
python -m opspilot.tasks.worker
```

该入口使用 Celery 默认的 `prefork` 池，使软/硬任务超时和 worker-lost 重投真正具备进程隔离语义。
每个子进程把指标写入 `PROMETHEUS_MULTIPROC_DIR`，父进程的 9100 端口聚合后交给
Prometheus；启动时只清理这个专用目录里的旧 `*.db` 指标文件，避免容器重启后重复计数。
worker 并发由 `OPSPILOT_WORKER_CONCURRENCY` 控制，默认值为 2。

worker 收到任务后：

1. 使用自己的异步 SQLAlchemy engine，避免跨事件循环复用 API 连接池。
2. 锁定事件行，将状态改为 `RUNNING`，追加 `task_started`。
3. 执行与内联模式相同的 `run_diagnosis`，因此模型、安全策略、审计结构完全一致。
4. 成功时提交终态；异常时回滚未完成诊断，写入 `FAILED` 和不含敏感错误正文的 `task_failed`。

Celery 开启了 late acknowledgement、worker-lost 重投和单任务预取。若进程在硬超时或崩溃后重投，同一个 `task_id` 可以从 `RUNNING` 恢复，并写入 `task_restarted`；不同任务 ID 不会抢占一个已运行事件。
`task_acks_on_failure_or_timeout=False` 防止父进程确认硬超时任务；未确认消息在
`OPSPILOT_BROKER_VISIBILITY_TIMEOUT_SECONDS` 到期后重新可见。普通业务异常不重入队列，
因为任务代码已先持久化 `FAILED` 和 `task_failed`，可避免确定性错误形成无限重试。
软超时信号可能从 asyncio 事件循环边界抛出，因此同步任务包装器会用新数据库会话将其明确
持久化为 `FAILED`；仅故障注入模式会忽略软超时，继续等待父进程执行硬超时。
任务发布不自动重试，Redis 连接与套接字超时均为 2 秒。这样 broker 中断时 API 会快速把
事件改为 `FAILED` 并记录 `task_dispatch_failed`，而不是让 HTTP 请求长时间悬挂或产生不透明重试。
任务状态与结果以 PostgreSQL 事件及轨迹为事实来源，因此 Celery 的 Redis result backend 不保存
诊断返回值；这也避免 broker 中断时发布端在无用的 result subscription 路径上继续重试。

`OPSPILOT_CHAOS_TASK_DELAY_SECONDS` 和 `OPSPILOT_CHAOS_IGNORE_SOFT_TIME_LIMIT` 是默认关闭
的故障注入开关，用于在已写入 `task_started` 后制造可控执行窗口。生产环境只要任一开关
启用就会拒绝启动，避免测试行为误入生产。
`scripts/verify_inflight_recovery.py` 使用只读源码挂载启动临时单并发 worker，杀死其唯一 prefork
子进程；另外两个脚本分别强杀整个容器和触发真实 Celery hard limit。所有脚本都在 `finally`
中恢复标准 worker。

## SSE 恢复

事件流仍以数据库中的追加式轨迹为事实来源。客户端可以使用：

```text
GET /api/v1/incidents/{incident_id}/events?after=12
Last-Event-ID: 15
```

服务端从两者较大的序号之后继续发送，并在空闲轮询时发送 SSE heartbeat。浏览器 `EventSource` 断线重连会自动携带最近的 `Last-Event-ID`，所以不会重放已经展示的轨迹。`task_queued`、`task_started`、`task_restarted` 和 `task_failed` 也会实时更新控制台状态。

## 验证

```bash
python -m pytest tests/integration/test_async_diagnosis.py -q
python -m ruff check .
python -m mypy opspilot apps/api
docker compose config
```

完整容器启动后，可用 `docker compose logs -f worker api` 同时观察投递和执行。生产部署还应增加队列长度、最老任务年龄、RUNNING 持续时间和失败率告警。
