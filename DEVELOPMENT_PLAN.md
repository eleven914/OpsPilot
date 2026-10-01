# OpsPilot 分阶段开发与学习计划

## 1. 范围理解

OpsPilot 的 MVP 是一个可私有化部署的企业 IT 运维故障处置 Agent。它通过 Web 控制台或 Alertmanager Webhook 接收事件，使用显式状态机调用监控、日志、CMDB、Runbook 和历史事件工具，输出可追溯到证据的诊断，并将所有变更动作置于人工审批之后，仅在模拟沙箱中执行。

本项目不连接真实生产 Kubernetes，不执行任意 Shell，不实现自动扩缩容、网络封禁、数据库写操作、复杂计费或移动端应用。模型训练配置和评测入口会交付，但任何性能数字都必须来自真实实验。

## 2. 总体技术路线

- 前端：React + TypeScript + Vite + Ant Design。
- 后端：Python 3.11 + FastAPI + Pydantic v2 + SQLAlchemy + Alembic。
- 状态与任务：自研显式 Agent 状态机；Celery + Redis 执行异步任务。
- 数据：PostgreSQL 16；Runbook 检索使用 pgvector。
- 模型：OpenAI-compatible 接口；本地开发默认 Mock Model，后续接入 vLLM。
- 安全：严格结构化输出、工具白名单、Schema 校验、RBAC、强制审批、预定义沙箱动作、完整追加式审计。
- 可观测：结构化 JSON 日志、OpenTelemetry、Prometheus、Grafana。
- 质量：pytest、pytest-asyncio、Playwright、类型检查、lint、GitHub Actions。

## 3. 阶段计划

### Phase 0：可运行基线与工程骨架

目标：无需 GPU，用一条命令启动最小闭环。

任务：

1. 建立 Monorepo、ADR、配置约定、`.env.example`、Makefile、Docker Compose 和 CI 骨架。
2. 初始化 FastAPI、React、PostgreSQL、Redis，以及数据库迁移基础设施。
3. 实现创建/查询事件的最小 API 和真实前后端联调，不以前端假数据替代接口。
4. 实现 Mock Model，以及 `query_metrics`、`query_logs`、`get_service_info`、`search_runbook`、`search_incidents` 五个 Mock 只读工具。
5. 实现三个可复现故障场景和最小完整 Agent 轨迹。
6. 同步编写状态机、工具 Schema、API 和关键集成测试。

教学重点：Monorepo 边界、依赖注入、Pydantic 校验、SQLAlchemy 会话、迁移、容器网络、前后端契约、为什么先做 Mock vertical slice。

阶段结果：`docker compose up` 后可创建事件，并在 Web 页面看到完整 Mock 轨迹；提交启动命令、测试结果、演示步骤和未完成项。按规格要求，此处暂停，等待阶段验收后才进入 Phase 1。

#### Phase 0 验收记录（2026-09-24）

- 状态：实现与本地验收完成，等待用户阶段确认。
- 后端：Ruff 通过；mypy strict 通过；pytest 6/6 通过；覆盖率 92.12%。
- 前端：ESLint 通过；TypeScript 与 Vite 生产构建通过；npm audit 0 个漏洞。
- 数据库：Alembic 在 SQLite 完成升级/降级往返；在隔离 PostgreSQL 库完成首次升级并生成预期三张表。
- 容器：PostgreSQL、Redis、API、Web 均启动；数据库与 Redis 健康；临时新 API 镜像自动迁移后 `/health` 返回 200。
- E2E：经 Nginx 创建/查询事件成功，事件状态为 `RESOLVED`，持久化 10 条轨迹。
- 非阻塞项：Vite 提示主 bundle 约 823 KB；FastAPI TestClient 依赖发出一条上游弃用警告。

### Phase 1：Agent、安全与审批闭环

目标：形成不可绕过审批的诊断与处置闭环。

任务：

1. 完成全部合法/非法状态转换、终止条件、错误恢复，以及 8 次模型推理、12 次工具调用、3 分钟执行预算。
2. 实现三类严格模型输出和最多一次 JSON 修复；禁止从自然语言提取隐式命令。
3. 完成 Tool Gateway：Schema、RBAC、超时、重试、熔断、脱敏、幂等和审计。
4. 完成证据引用、追加式轨迹、审批队列、申请人与审批人隔离，以及预定义沙箱执行器。
5. 实现 `restart_service`、`rollback_deployment`，并补齐 12 类故障场景。
6. 完成事件详情、审批中心和 SSE 轨迹页面；补齐安全、集成与 E2E 测试。

教学重点：有限状态机、不变量、命令/查询分离、零信任工具边界、Prompt Injection 防御、幂等、审批工作流、SSE。

阶段结果：只读诊断和审批通过/拒绝/过期路径 E2E 通过；未知工具、非法参数、自审批和未经批准的变更均被拒绝。

#### Phase 1 里程碑 1-2 进展（2026-09-24）

- 已完成完整状态转换表、执行预算、三类结构化模型输出和 Safety Guard。
- 已完成 Agent Run、Tool Call、Evidence、Approval 的模型与迁移。
- 已完成 viewer/operator/approver/admin RBAC、申请人与审批人隔离。
- 已完成 `restart_service`、`rollback_deployment` 预定义沙箱动作及审批通过/拒绝闭环。
- 已完成审批中心前端的风险、证据、参数、回滚方案展示与决策操作。
- 已完成只读工具超时、有限重试、按工具熔断、异常映射、输出裁剪和敏感信息脱敏。
- 已完成变更工具幂等键缓存、审批过期自动扫描和事件轨迹 SSE 接口。
- 已完成规格要求的 12 类数据驱动故障场景，以及场景与指标、日志、拓扑、Runbook、根因和动作的一致性测试。
- 已完成严格模型 JSON 解析、最多一次修复、禁止 Markdown/自然语言命令提取和多余字段拒绝。
- 已完成 operator 事件级隔离，以及创建事件到批准执行再到验证恢复的 Playwright Chromium E2E。
- 已完成 Alertmanager Webhook、事件消息接口、浏览器批准/拒绝/过期 E2E，以及 Phase 1 教程和验收复盘。

#### Phase 1 验收记录（2026-09-25）

- 状态：功能实现完成，进入阶段验收。
- API：事件创建/查询/消息、SSE、Alertmanager Webhook、审批列表/批准/拒绝均已实现。
- Agent：完整状态机、预算、严格 JSON、单次修复、证据约束和 12 类数据驱动场景已实现。
- 安全：RBAC、事件级授权、自审批拒绝、强制审批、无 Shell 沙箱、幂等、脱敏、超时/重试/熔断已实现。
- 数据：三版 Alembic 迁移完成升级、全量回滚、再次升级验证。
- 浏览器：批准执行、拒绝和审批过期三条 Chromium E2E 已通过。
- 教程：已提供完整 Phase 1 初学者教程与复习题答案。
- 已知非阻塞项：Vite 主包约 825 KB；TestClient 存在一条上游弃用警告；真实认证代理和 Redis SSE 分发留待后续阶段。

### Phase 2：数据、训练配置与可复现评测

目标：交付可复现的 Base、SFT、SFT+DPO 三组评测链路。

任务：

1. 构建按故障模板/服务隔离的数据生成、校验、去重和切分流程。
2. 交付 LlamaFactory QLoRA SFT 与 DPO 配置、版本记录和模型导出脚本。
3. 实现工具选择、参数合法率、不安全动作、证据精度、任务成功率、幻觉率等评测器。
4. 实现三组模型使用相同独立测试集的评测入口与报告页面。
5. 在可用算力允许时运行真实实验；没有算力时仅证明流水线可运行，不填写虚假提升数字。

教学重点：SFT/DPO 原理、QLoRA、数据泄漏、偏好对构造、离线评测可信度、可复现实验元数据。

阶段结果：训练与评测命令、配置和数据卡可复现；报告只展示真实测得的数据。

#### Phase 2 里程碑 1 进展（2026-09-25）

- 已完成严格 SFT/DPO 数据 Schema、12 场景程序化生成器和 JSONL 输出器。
- 已完成服务级隔离切分：train、validation、test 的服务和故障模板均无交集。
- 已完成 ID/内容去重、Schema、安全偏好和最小规模验证。
- 默认实测生成 SFT 8,064 条、DPO 2,040 对、独立 SFT 测试集 1,344 条。
- 已生成带文件 SHA-256 的版本清单；当前数据明确标记为尚未人工审核，不可用于最终性能宣称。
- 已完成离线评测器、严格预测覆盖校验、冻结测试集哈希和统一 JSON 报告。
- 已完成 Base、SFT、SFT+DPO 三组公平比较门禁；数据或生成参数不同时拒绝比较。
- 已完成 LlamaFactory v0.9.5 QLoRA SFT/DPO 配置、官方格式转换、实验元数据和双模型导出配置。
- GPU 正式实验已于 2026-09-28 完成，原始报告和实验清单已版本化，详见 `docs/PHASE2_EXPERIMENT_REPORT.md`。

#### Phase 2 验收记录（2026-09-28）

- 状态：训练、三组公平评测与结果固化完成，进入 Phase 3。
- 环境：AutoDL RTX 4080 32GB、PyTorch 2.5.1+cu124、CUDA 12.4、LlamaFactory 0.9.5。
- SFT：5,376 条训练样本、1,344 条验证样本，3 epochs/1,008 steps；训练损失 `0.0258318440`，验证损失 `0.0000032358`。
- DPO：1,360 对训练数据、340 对验证数据，3 epochs/255 steps；偏好验证准确率 `1.0`，chosen/rejected 奖励间隔 `13.2485781`。
- 公平门禁：Base、SFT、SFT+DPO 使用相同 v0.2 测试集 SHA-256、`temperature=0` 和 `max_tokens=1024`，比较报告标记 `comparable: true`。
- 冻结测试：Base 有效决策率 `16.67%`、任务成功率 `0%`；SFT 与 SFT+DPO 的有效决策率和任务成功率均为 `100%`，且危险操作率与幻觉率均为 `0%`。
- 解释边界：测试集是规则验证但未人工审核的合成数据；结果证明流水线和域内契约学习效果，不代表真实生产准确率。DPO 在偏好集上完全区分且未造成冻结测试回归，但饱和测试无法证明其相对 SFT 的额外线上收益。

### Phase 3：模型服务化、可观测与韧性

目标：接入真实 OpenAI-compatible/vLLM 服务并量化工程表现。

任务：

1. 实现 Model Gateway、超时、降级和 Mock/真实模型切换。
2. 完善 Celery 异步任务、SSE 恢复、服务依赖故障恢复。
3. 接入 OpenTelemetry、Prometheus、Grafana 和结构化日志。
4. 执行负载、恢复与资源测试，产出 P50/P95、错误率、token、成本和资源占用报告。

教学重点：异步任务语义、分布式追踪、RED/USE 指标、背压、超时与重试放大、性能测试方法。

阶段结果：真实测量报告、Grafana 面板、故障恢复记录；指标不可用时明确标记缺失原因。

#### Phase 3 里程碑 1 进展（2026-09-28）

- 已实现异步 OpenAI-compatible Chat Completions 客户端，固定 `temperature=0` 并记录 token 与模型延迟。
- 已实现真实模型证据循环：5 次只读工具决策、终局诊断/变更建议、严格 JSON 解析和最多一次修复。
- 已将训练期 v0.2 System Policy 提取为运行时共享契约，并验证数据生成结果不应因代码搬迁改变。
- 已实现 `mock` / `openai_compatible` 配置切换；真实模型超时、上游错误、非法输出、预算或安全策略失败时可审计地降级到 Mock。
- 已确保模型看不到模拟器内部 `scenario_id`，该值只在 Tool Gateway 执行边界注入。
- 下一里程碑：Celery/Redis 异步任务与 SSE 恢复，然后接入 OpenTelemetry、Prometheus、Grafana 和负载测试。

#### Phase 3 里程碑 2-3 进展（2026-09-28）

- 已实现可切换的 inline/Celery 诊断，Docker 默认使用 Redis 队列和独立 worker。
- 已实现任务投递、开始、失败和 worker-lost 重投轨迹，以及 SSE `Last-Event-ID` 恢复与 heartbeat。
- 已实现结构化 JSON 日志、请求 ID、trace/span 关联和低基数 HTTP 日志字段。
- 已实现 API、诊断、Celery、模型请求、token 和 Mock 降级 Prometheus 指标。
- 已接入 FastAPI、HTTPX、Celery OpenTelemetry instrumentation，经 Collector 写入 Tempo。
- 已提供自动配置的 Prometheus、Tempo、Grafana 数据源和 OpsPilot Overview 面板。
- 下一里程碑：执行负载、故障恢复和资源测试，固化真实 P50/P95、错误率、token 与资源报告。

Phase 3 容器验证补充（2026-09-28）：九个服务实际启动，HTTP/队列完成基线、
worker 停止后排队恢复、Prometheus 抓取和 API→worker→Tempo 追踪已验证。
worker 已切换为 prefork 并接入 Prometheus 多进程聚合；Redis 中断可在 4.078 秒内
审计失败并于恢复后继续处理新任务；执行中的 prefork 子进程被 SIGKILL 后，同一 task ID
可写入 `task_restarted` 并最终完成。整容器 SIGKILL 通过 Redis visibility timeout 恢复，
Celery 60 秒 hard limit 也已实测重投并完成；正常 soft limit 会持久化为 FAILED，避免悬挂。
真实模型成本核算已改为显式的 input/output 每百万 token 单价，成功运行会持久化
`model_usage` 审计轨迹；HTTP 基准脚本可直接汇总 token、估算成本与模型延迟 P50/P95。
详细容器实测见 `docs/PHASE3_CONTAINER_VALIDATION.md`。

#### Phase 3 实机验收记录（2026-10-02）

- AutoDL RTX 4080 32GB 上使用 vLLM 0.30.0、Qwen3-4B-Instruct-2507 和 SFT+DPO LoRA；真实模型 API 单事件闭环返回 HTTP 201、`RESOLVED`、预期五工具顺序与模型用量轨迹，Mock 回退次数为 0。
- 修复客户端 30 秒固定读取超时、SQLite 在模型等待期间持有写事务，以及真实模型所需的工具顺序约束；本地 261 项测试通过。
- 固定工作负载下，并发 1/2/4 各 4 请求全部成功；整组耗时分别为 198.97/106.68/55.71 秒，请求 P95 约 55.09/53.40/55.63 秒，并有 1 Hz GPU 利用率、显存、功耗和温度记录。详见 `docs/LIVE_GPU_VALIDATION_2026-10-02.md`。
- 成本字段记录为 `unpriced`，因为未配置 token 单价；不能把估算值 0 美元解释为零成本。CPU/主机内存未采样，每档 4 个样本不足以推断容量上限或 P99。
- Phase 3 的工程目标已完成；服务自启、长期持久化数据库、真实身份代理与更高并发容量不在本轮验收范围，转入后续部署工作。

### Phase 4：开源质量与 GitHub 交付

目标：让新用户能在 30 分钟内理解、启动和验证项目。

任务：

1. 完善 README、架构/API 文档、ADR、数据卡、模型卡、实验报告、限制和演示材料。
2. 完成安全扫描、许可证/依赖检查、CI 门禁和发布前密钥检查。
3. 导出单事件 JSON 审计报告，跑通全部 12 个场景和核心 E2E。
4. 在用户授权的 GitHub 账户或组织下创建/绑定仓库，推送代码并核验远程提交与 CI。
5. 选择真实上游 Issue，提交可公开核验的贡献；这是外部协作动作，执行前单独确认目标与内容。

教学重点：开源仓库治理、CI/CD、语义化提交、供应链安全、发布清单、如何写高质量 Issue/PR。

阶段结果：GitHub 仓库 URL、可复现版本标签、CI 结果、启动与演示说明，以及公开可核验的上游 Issue/PR。

#### Phase 4 本地交付进展（2026-10-02）

- README 已链接真实 GPU 实测报告并说明部署边界；新增有事件级访问控制的单事件 JSON 审计导出接口及集成测试。
- 12 个数据驱动场景均经 API 集成测试验证；后端 274 项测试通过，核心模块覆盖率 87.50%，Ruff、mypy 通过。
- 前端 ESLint、TypeScript/生产构建通过；批准、拒绝、过期三条浏览器 E2E 通过，CI 已补入 E2E 作业。构建仍提示主 bundle 约 826 KB。
- `npm audit` 报告 0 个漏洞，`pip check` 无依赖冲突；常见私钥/token 特征扫描未命中。Python 漏洞数据库扫描尚未完成，发布前仍需执行；扫描不等于保证绝无密钥。
- 已选择 Apache-2.0 许可证，目标为账号 `eleven914` 下的公开 GitHub 仓库。建仓与推送待完成；对外提交上游 Issue 的目标和内容尚未确认。远端 AutoDL 服务未在本轮重新部署审计导出接口。

## 4. 每阶段固定工作方式

每个阶段都按同一闭环推进：

1. 课前导读：说明本阶段解决的问题、核心概念和关键取舍。
2. 设计：先写接口、数据流、安全边界和验收测试，再实现代码。
3. 实现：按最小纵向切片逐步提交，每个关键模块都解释实现原理。
4. 验证：运行 lint、类型检查、单元测试、集成测试和必要的 E2E；记录真实结果。
5. 复盘：给出文件导航、关键代码阅读顺序、常见陷阱、练习题和阶段验收清单。
6. 门禁：只有当前阶段验收通过，才进入下一阶段。

## 5. 关键风险与控制

- 范围膨胀：以规格的 MVP 必做/不做清单为边界，新增想法进入 backlog。
- 安全绕过：所有动作只能经 Tool Gateway 和审批记录执行；没有任意 Shell 接口。
- “有结论无证据”：最终答案必须引用持久化证据 ID；无证据标记信息不足。
- Mock 与真实系统脱节：工具共享同一接口与契约测试，适配器只替换数据源。
- 数据泄漏：按故障模板和服务切分，而不是随机逐条切分。
- 训练资源不足：训练配置、数据和评测先可复现，真实数值只在有算力时填写。
- 环境差异：Docker Compose 固化依赖，CI 从干净环境启动并测试。
- GitHub 权限：本地开发不依赖 GitHub；最终推送前确认账号/组织、仓库可见性和授权状态。

## 6. 最终 Definition of Done

- 一条 Docker Compose 命令启动开发环境。
- 12 个故障场景可重复运行，诊断均可追踪到证据和工具调用。
- 所有变更都经过审批，且只能在模拟沙箱执行。
- Base、SFT、SFT+DPO 使用同一独立测试集评测。
- 支持导出单事件 JSON 审计报告。
- CI 执行 lint、类型检查、单元、集成和关键 E2E 测试。
- 核心 Python 模块覆盖率至少 80%，安全策略至少 90%。
- 仓库不含真实密钥、企业日志或不可公开数据。
- GitHub 远程仓库可访问，README 能指导新用户在 30 分钟内启动。
