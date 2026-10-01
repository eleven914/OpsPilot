# OpsPilot

OpsPilot 是一个证据优先、可私有化部署的 IT 故障处置 Agent。Phase 2 的训练与公平评测、Phase 3 的真实 GPU 模型服务与工程验证已完成；项目正在进行 Phase 4 的开源交付准备。应用运行时仍默认使用 Mock Model，配置真实模型端点后可切换到已训练模型。

项目源码按 [Apache License 2.0](LICENSE) 发布，版权声明见 [NOTICE](NOTICE)；第三方依赖、基础模型及其权重仍分别遵循各自的许可条款。仓库不包含训练后的模型权重。

项目源码按 [Apache License 2.0](LICENSE) 发布；第三方依赖、基础模型及其权重仍分别遵循各自的许可条款。仓库不包含训练后的模型权重。

## 快速启动

要求：Docker Desktop、Docker Compose，以及可用的 8000/5173 端口。

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

启动后访问：

- Web 控制台：<http://localhost:5173>
- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>

API 容器会先执行 `alembic upgrade head`，再启动 Uvicorn。首次启动需下载基础镜像和依赖，后续会使用缓存。

## 本地质量检查

```powershell
python -m pip install -e ".[dev]"
python -m ruff check .
python -m mypy opspilot apps/api
python -m pytest --cov=opspilot --cov=apps.api --cov-fail-under=80

Set-Location apps/web
npm ci
npm run lint
npm run build

# 首次运行 E2E 时，将浏览器安装到 E 盘
$env:PLAYWRIGHT_BROWSERS_PATH="E:\OpsPilotRuntime\playwright-browsers"
npx playwright install chromium
npm run e2e
```

## 演示流程

1. 打开 Web 控制台。
2. 输入事件标题、服务、严重级别和现象描述。
3. 点击“启动 Mock 诊断”，查看状态转换、工具参数、数据来源和证据 ID。
4. 对 `gateway` 或 `order` 场景，在“待审批动作”中核对风险、参数、证据和回滚方案。
5. 点击“批准并执行”或“拒绝”，观察后续执行、验证和终态轨迹。
6. 刷新页面，确认事件、审批和轨迹仍由 PostgreSQL 返回。

## 当前架构

- `apps/api`：FastAPI 接口与依赖注入。
- `apps/web`：React、TypeScript、Vite、Ant Design 控制台。
- `opspilot/agent`：显式 Agent 状态机和确定性编排器。
- `opspilot/model_gateway`：OpenAI-compatible/vLLM 异步客户端、超时与响应错误边界。
- `opspilot/tasks`：Celery/Redis 诊断任务、worker 丢失重投和可审计失败处理。
- `opspilot/observability`：JSON 日志、Prometheus RED 指标和 OpenTelemetry trace。
- `opspilot/tools`：工具白名单、Pydantic Schema、Mock Tool Gateway 与无 Shell 沙箱动作。
- `opspilot/tools/resilience.py`：只读工具的超时、有限重试、熔断、异常映射和输出脱敏。
- `opspilot/security`：viewer/operator/approver/admin 的 RBAC 权限定义。
- `opspilot/models`：事件、Agent Run、工具调用、证据、审批和追加式轨迹模型。
- `simulator/scenarios`：12 类可复现故障场景及其证据、拓扑和安全处置定义。
- `migrations`：Alembic 数据库迁移。
- `tests`：单元和 API 集成测试。

详细阶段计划见 [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md)，架构取舍见 [`docs/adr/0001-phase-0-architecture.md`](docs/adr/0001-phase-0-architecture.md)。

如果你只有 Python 语法基础，请按顺序阅读 [`docs/PHASE0_BEGINNER_TUTORIAL.md`](docs/PHASE0_BEGINNER_TUTORIAL.md)。它从一次请求的完整生命周期开始，逐层讲解项目架构、模块实现、设计原因、常见错误和动手练习。

Phase 1 的场景矩阵、严格模型 JSON、事件级授权和浏览器 E2E 原理见 [`docs/PHASE1_MILESTONE3_GUIDE.md`](docs/PHASE1_MILESTONE3_GUIDE.md)。

Phase 1 的完整初学者教程、核心不变量和复习题答案见 [`docs/PHASE1_BEGINNER_TUTORIAL.md`](docs/PHASE1_BEGINNER_TUTORIAL.md)。

Phase 2 合成数据的数据卡与泄漏控制说明见 [`data/DATA_CARD.md`](data/DATA_CARD.md)，使用 `python scripts/generate_training_data.py` 可复现生成带 SHA-256 清单的 SFT/DPO 数据。

离线评测指标、预测格式和三组公平比较门禁见 [`evaluation/README.md`](evaluation/README.md)。

QLoRA SFT/DPO 数据转换、训练、实验记录和导出步骤见 [`training/README.md`](training/README.md)。

Phase 2 的硬件、训练指标、三组对照结果、失败分析和适用边界见 [`docs/PHASE2_EXPERIMENT_REPORT.md`](docs/PHASE2_EXPERIMENT_REPORT.md)。版本化原始报告位于 [`evaluation/reports/experiments/opspilot-synthetic-v0.2/`](evaluation/reports/experiments/opspilot-synthetic-v0.2/)。

Phase 3 的 Mock/真实模型切换、OpenAI-compatible 请求契约、严格 JSON 修复与安全降级见 [`docs/PHASE3_MODEL_GATEWAY.md`](docs/PHASE3_MODEL_GATEWAY.md)。

Phase 3 的 Celery 后台诊断、任务状态轨迹与 SSE 断点续传见 [`docs/PHASE3_ASYNC_TASKS.md`](docs/PHASE3_ASYNC_TASKS.md)。

Phase 3 的结构化日志、Prometheus/Grafana 面板和 OpenTelemetry/Tempo 链路见 [`docs/PHASE3_OBSERVABILITY.md`](docs/PHASE3_OBSERVABILITY.md)。

真实 GPU 服务的 HTTP 延迟、错误率、token 与 GPU 资源实测见 [`docs/LIVE_GPU_VALIDATION_2026-10-02.md`](docs/LIVE_GPU_VALIDATION_2026-10-02.md)。每档仅 4 个请求，报告明确列出统计与成本边界。

单事件 JSON 审计报告可通过 `GET /api/v1/incidents/{incident_id}/audit` 下载，包含事件、完整轨迹、模型运行、工具调用、证据与审批记录；访问权限与事件详情相同。例如：

```bash
curl -H 'X-User-Id: demo-operator' -H 'X-Role: operator' \
  -o incident-audit.json \
  http://localhost:8000/api/v1/incidents/INCIDENT_ID/audit
```

## 当前限制

- 默认配置仍使用 Mock Model；设置 `OPSPILOT_MODEL_PROVIDER=openai_compatible` 后才会调用配置的 vLLM/OpenAI-compatible 服务。
- 工具只读取确定性模拟数据，尚未连接真实监控、日志或 CMDB。
- 当前身份由演示用请求头提供，生产部署必须由可信认证代理签发身份。
- 当前 SSE 以数据库轮询保证可恢复性；Redis 用于 Celery 任务队列，尚未作为瞬时事件广播总线。
- Alertmanager Webhook 和事件消息已接入后台诊断；真实认证代理仍留待后续阶段。
- 前端生产包目前约 825 KB，后续通过路由懒加载与分包优化。
- 不包含真实密钥、企业日志或生产系统写权限。
- AutoDL 实机验证使用手动启动的 vLLM/API 和单机 SQLite；该环境不是已完成的长期运行或生产部署方案。
