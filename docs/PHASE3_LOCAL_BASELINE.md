# Phase 3 本地性能基线（2026-09-28）

使用 `python scripts/benchmark_local.py --requests 40 --concurrency 4` 实测。
测量时间为 2026-09-28T08:54:27Z，基于 c69b80f 加本轮基准脚本工作区。
环境为 Windows 10.0.26200、Python 3.11.9。

| 项目 | 实测值 |
| --- | ---: |
| 请求数 / 并发数 | 40 / 4 |
| 完成请求吞吐 | 29.95 次/秒 |
| P50 | 70.85 ms |
| P95 | 282.51 ms |
| 最大延迟 | 906.34 ms |
| HTTP 或诊断状态错误 | 0 / 40 |
| 总测量时长 | 1.336 秒 |

这是进程内 HTTPX ASGITransport、隔离 SQLite、inline 和 Mock 的短时基线。
每次运行创建临时数据库并在退出时清理，不读取项目配置中的数据库。
请求创建 inventory 只读模拟诊断，成功标准同时要求 HTTP 201 和 RESOLVED。
延迟覆盖请求处理与数据库提交，不包含客户端等待并发槽位的时间；
P50/P95 使用排序后的线性插值。仅健康检查预热，首个诊断也计入结果。
此结果不能用于推断真实模型、PostgreSQL、Celery 或生产网络性能。

脚本向标准输出打印 JSON，包括每个请求的原始延迟、状态、运行环境和限制。
GPU 显存、进程内存、真实 token 与成本均为 null，表示未测量。

Docker 检查失败：docker_engine 命名管道不存在，当前 daemon 未运行。
因此整套容器、Redis 中断恢复、worker 重启恢复、OTLP 到 Tempo 的实际链路
及资源占用验证尚未完成。现有故障路径集成测试使用模拟投递和直接 worker 函数，
不能替代真实消息代理故障演练。

当前 Compose worker 使用 threads 池；Celery 配置的 soft/hard time limit
不能视作已验证的线程任务终止保证。进入恢复验收前，应恢复进程隔离并配套
多进程指标采集，或实现可验证的任务截止时间与卡住任务处理机制。
