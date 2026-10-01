# Docker 实测记录：2026-09-28

基于 c69b80f 与本轮测试脚本、审批列表刷新修复，Docker Desktop / WSL2，
PostgreSQL 16、Redis 7、Celery prefork（并发 2）、Mock 模型。
本轮九个服务均已实际启动，原有数据卷保留。

## 启动修复

首次 pip 构建解析失败；相同依赖重试安装成功，没有更改版本范围。
已有数据库仅包含第一版 incidents、trace_events 表，没有 alembic_version。
只读核对列类型、主外键及索引与 20260924_0001 完全一致后，执行
`docker compose run --rm --no-deps api alembic stamp 20260924_0001`，
再启动 API 自动升级至 20260925_0003。原有一条事件、十条轨迹未删除。
这是一项针对已验证结构的环境修复，不应对未知数据库盲目 stamp。

## HTTP 与异步完成基线

命令：`python scripts/benchmark_http.py --requests 20 --concurrency 4`。
测量完成时间 2026-09-28T09:36:37Z。

| 指标 | 实测 |
| --- | ---: |
| 请求数 / 客户端并发 | 20 / 4 |
| HTTP 成功且最终 RESOLVED | 20 / 20 |
| 错误率 | 0% |
| 诊断完成 P50 | 2313.36 ms |
| 诊断完成 P95 | 3966.97 ms |
| 总耗时 | 12.405 s |
| 成功诊断吞吐 | 1.612 / s |

完成时间包含 HTTP、Redis 排队、worker、PostgreSQL 持久化及 100 ms 轮询观测。
脚本分别输出 accept_ms 与 completion_ms；不把入队计作完成。
闭环并发，不含等待并发槽位的时间。20 次短测只证明该环境基线，不是容量上限。
真实模型 token、成本和 GPU 显存未测量。

2026-09-29 增加模型用量报告后，使用最新 API/worker 镜像执行 4 请求、并发 2 的回归：
4/4 最终 `RESOLVED`，错误率 0，完成 P50 221.04 ms、P95 349.83 ms。由于仍为 Mock，
报告明确输出 `measured_runs=0`、`model_latency_ms=null` 和
`pricing_status=not_measured`，不会把缺失的真实模型指标伪装成零成本实测值。

## 恢复验证

命令：`python scripts/verify_worker_recovery.py`。
脚本只控制本项目 worker，并在 finally 中启动恢复。

- 事件：6d2817c5-a743-4cfc-aecf-72aacdb1c518。
- worker 停止时创建事件返回 QUEUED。
- 启动后 2.297 秒观测到 RESOLVED。
- task_queued 与 task_started 的 task_id 一致，开始事件仅一次。

这是优雅停止后的排队恢复。

### 执行中子进程崩溃

命令：`python scripts/verify_inflight_recovery.py`。脚本停止标准 worker，启动默认关闭延迟的
临时单并发 prefork worker；事件进入 RUNNING 后，对唯一子进程发送 SIGKILL。临时容器使用
唯一名称且只读挂载当前源码，`finally` 无条件停止临时容器并恢复标准 worker。

- 事件：3740af72-5ef6-4f99-a69b-7ce9492b1d51。
- task ID：5fc7e6b4-9478-427d-ae95-48f84ef03609。
- 轨迹严格为 `task_started`、`task_restarted`，两者 task ID 相同。
- 杀死子进程后 10.187 秒最终 RESOLVED。

这验证了父 worker 存活时的子进程丢失重投。

### 整个 worker 容器强杀

命令：`python scripts/verify_worker_container_crash.py`。事件进入 RUNNING 后，对临时 worker
容器发送 SIGKILL，随后立即启动标准 worker。Redis 在 visibility timeout 后恢复未确认消息。

- 事件：6b5581c8-16e5-4981-806d-adc6af3007cb。
- task ID：13dec30b-1b9f-4f8f-bec7-ea196d33f945。
- 同一 task ID 形成 `task_started`、`task_restarted`，92.750 秒后 RESOLVED。

### 软/硬任务超时

命令：`python scripts/verify_hard_timeout_recovery.py`。临时 worker 设置 soft=30 秒、hard=60 秒，
首次执行注入 70 秒延迟。同步任务包装器仅在测试模式忽略 soft limit，让 Celery 父进程实际执行
hard limit；重投时跳过故障延迟。

- 最终事件：daab2630-7817-4a1d-bdc7-85f8938373b3。
- task ID：ba5a7620-2cfb-45aa-918a-cf04f213ccc5。
- Celery 日志明确包含 `Hard time limit (60s) exceeded`。
- 同一 task ID 形成 `task_started`、`task_restarted`，60.657 秒后 RESOLVED。
- 前置失败实验揭示两处真实缺陷：应用级 time limit 未自动绑定到任务对象，以及 soft-limit
  信号从 asyncio selector 边界抛出。现已显式绑定任务限制，并让正常 soft timeout 使用新会话
  写入 `FAILED + task_failed`；所有失败实验事件均以原 task ID 补投并最终 RESOLVED。

### Redis 中断

命令：`python scripts/verify_redis_outage.py`。脚本停止本项目 Redis，并始终在
`finally` 中启动恢复。最初两次实验发现 Celery Redis result backend 会在发布前
进行 20 次重试，使 HTTP 请求超过 15 秒；这证明仅关闭 publish retry 不足以快速失败。
由于 OpsPilot 以 PostgreSQL 事件和轨迹为事实来源、从不读取 Celery 返回值，最终将
任务发布及 worker 任务都设为 `ignore_result=True`，并使用单次、2 秒超时的专用发布连接。

最终实测：

- 事件：964ee27c-ee67-4b34-91ba-e41ddbb36e6d。
- Redis 停止时 API 在 4.078 秒返回 HTTP 503。
- 事件状态为 FAILED，最后轨迹为 `task_dispatch_failed`。
- Redis 自动恢复为 healthy；随后事件 3cbc067a-f718-472d-9a2a-40e5064d52f0
  正常从 QUEUED 进入 RESOLVED，证明 worker 已重连。

### Prefork 与多进程指标

worker 已从 threads 改为 prefork，并实际核验父进程下有 2 个子进程。这样 Celery
软/硬超时具备进程隔离基础。Prometheus client 使用多进程目录，9100 聚合端点在执行
一次任务后暴露 `opspilot_task_runs_total{outcome="resolved"} 1` 和 duration count 1；
Prometheus 查询 API 与 worker 的 `up` 均为 1。子进程崩溃、整容器强杀和 hard limit
三种路径均已完成专项注入验证。

## 监控与链路

- Prometheus /api/v1/targets：opspilot-api 与 opspilot-worker 均 up，lastError 为空；
  Redis 恢复后再次查询两者 `up` 均为 1。
- Grafana /api/health：database=ok，版本 11.2.2。
- Tempo 搜索返回实际 trace；读取 b612601901dda702752e18f57ce1146c，
  确认同时包含 opspilot-api 与 opspilot-worker 的 spans。

`docker compose stats --no-stream` 测试后单次内存快照：

| 容器 | MiB |
| --- | ---: |
| API | 89.54 |
| worker | 92.97 |
| PostgreSQL | 55.54 |
| Redis | 8.168 |
| Collector | 30.68 |
| Tempo | 56.95 |
| Prometheus | 21.13 |
| Grafana | 48.37 |
| Web | 12.23 |

此快照不代表压力期间的峰值。测试事件保留在数据库中供审计，标题以
HTTP benchmark 或 Worker recovery probe 标识。
