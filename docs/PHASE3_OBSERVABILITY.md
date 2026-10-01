# Phase 3：日志、指标与分布式追踪

本里程碑为 API、Celery worker 和模型网关建立同一套可观测信号。目标不是只把组件启动起来，而是让一次事件从 HTTP 接入、任务投递、worker 执行到模型调用都可以定位、计数和量化。

## 启动与入口

```bash
docker compose up --build -d
docker compose ps
```

- OpsPilot：<http://localhost:5173>
- API 原始指标：<http://localhost:8000/metrics>
- Prometheus：<http://localhost:9090>
- Grafana：<http://localhost:3000>，默认账号 `admin` / `opspilot`

生产环境必须通过 `GRAFANA_ADMIN_PASSWORD` 修改默认密码。Grafana 已自动配置 Prometheus、Tempo 和 `OpsPilot Overview` 面板，无需手工导入。

## 结构化日志

`ObservabilityMiddleware` 为请求生成或接受最长 128 字符的 `X-Request-ID`，将它写回响应，并通过 `contextvars` 注入同一请求中的 JSON 日志。字段包含：

- `timestamp`、`level`、`logger`、`message`
- `request_id`
- OpenTelemetry 激活时的 `trace_id`、`span_id`
- HTTP method、模板化 route、status 和 duration
- worker 日志中的 incident、task 和 outcome

日志不使用原始 URL 作为指标标签，避免事件 ID 造成高基数；异常日志记录异常类型和堆栈，但任务审计轨迹只保存错误类型，不把可能含密钥的异常正文写入数据库。

## Prometheus 指标

API `/metrics` 暴露 HTTP、诊断和模型指标。worker 在容器内部 `9100` 端口暴露自己的任务指标，Prometheus 同时抓取两者。

核心指标：

- `opspilot_http_requests_total`
- `opspilot_http_request_duration_seconds`
- `opspilot_diagnosis_runs_total`
- `opspilot_diagnosis_duration_seconds`
- `opspilot_task_runs_total`
- `opspilot_task_duration_seconds`
- `opspilot_model_requests_total`
- `opspilot_model_request_duration_seconds`
- `opspilot_model_tokens_total`
- `opspilot_model_estimated_cost_usd_total`
- `opspilot_model_fallbacks_total`

Celery 使用 `--pool=threads`，让并发任务和 worker 指标 HTTP 服务处于同一进程。否则 prefork 子进程中的指标不会自动出现在父进程的 `/metrics`。

## OpenTelemetry 与 Tempo

FastAPI、HTTPX 和 Celery 使用自动 instrumentation。OTLP/HTTP spans 发送到 OpenTelemetry Collector，Collector 批量转发到 Tempo；Grafana Explore 可按 trace ID 查询。`service.name` 分别是 `opspilot-api` 与 `opspilot-worker`。

本地不启动 Collector 时，代码默认关闭 OTLP 导出；Compose 会显式设置 `OPSPILOT_OTEL_ENABLED=true`。这避免普通单元测试尝试连接外部服务。

## 验证与告警建议

```bash
python -m pytest tests/integration/test_observability.py -q
python -m ruff check .
python -m mypy opspilot apps/api
docker compose config
```

下一里程碑的负载测试应以这些指标生成真实的 P50/P95、错误率、token 消耗和资源报告。建议生产告警至少覆盖：HTTP 5xx 比率、诊断失败率、任务最老年龄、模型超时/降级率和 P95 延迟。
