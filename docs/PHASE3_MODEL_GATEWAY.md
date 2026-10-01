# Phase 3 模型服务化：Model Gateway

## 1. 这一阶段解决什么问题

Phase 1 的 API 无论环境变量如何设置，都会直接实例化 `MockOrchestrator`。Phase 3
里程碑 1 把模型访问、Agent 决策和数据库持久化分成三个边界，使同一套 Agent 可以在开发时
使用 Mock，在部署时切到 vLLM 或其他 OpenAI-compatible 服务。

```text
Incident API
    -> run_diagnosis（选择 provider、持久化运行指标）
        -> MockOrchestrator
        或
        -> LiveOrchestrator（状态机、预算、严格决策、安全策略）
            -> OpenAICompatibleClient（HTTP、超时、响应解析）
            -> ToolGateway（Schema、白名单、韧性、审计）
```

模型永远不能直接执行 Shell 或变更工具。`restart_service` 和
`rollback_deployment` 只能形成 `proposed_action`，之后仍经过既有审批和预定义沙箱执行路径。

## 2. 配置

默认配置保持 Mock，不需要 GPU：

```dotenv
OPSPILOT_MODEL_PROVIDER=mock
```

连接 OpenAI-compatible/vLLM：

```dotenv
OPSPILOT_MODEL_PROVIDER=openai_compatible
OPSPILOT_MODEL_BASE_URL=http://model:8000/v1
OPSPILOT_MODEL_API_KEY=replace-me
OPSPILOT_MODEL_NAME=Qwen/Qwen3-4B-Instruct-2507
OPSPILOT_MODEL_VERSION=opspilot-sft-dpo-v0.2
OPSPILOT_MODEL_TIMEOUT_SECONDS=30
OPSPILOT_MODEL_MAX_TOKENS=1024
OPSPILOT_MODEL_INPUT_COST_PER_MILLION_TOKENS=0
OPSPILOT_MODEL_OUTPUT_COST_PER_MILLION_TOKENS=0
OPSPILOT_MODEL_FALLBACK_TO_MOCK=true
```

`MODEL_NAME` 必须与模型服务接受的 `model` 字段一致。API key 使用 Pydantic
`SecretStr` 保存；异常和审计事件不会输出 key 或上游响应正文。
两个成本配置使用服务商公布的每百万 token 美元单价；默认 `0` 表示尚未定价，系统不会猜测
可能随时间或部署方式变化的价格。

## 3. 请求契约

客户端调用：

```text
POST {MODEL_BASE_URL}/chat/completions
```

固定发送 `temperature=0.0`、`stream=false` 和配置的 `max_tokens`。响应必须至少包含：

```json
{
  "model": "served-model",
  "choices": [{"message": {"content": "{...严格 JSON 决策...}"}}],
  "usage": {"prompt_tokens": 100, "completion_tokens": 50}
}
```

HTTP 超时、连接错误、非 2xx 状态、空 choices 或空 content 会被映射为项目自己的
`ModelGatewayError` 子类。外部错误正文不会传入用户响应。

## 4. 真实模型决策循环

`LiveOrchestrator` 使用与 v0.2 训练数据完全相同的 System Policy：

1. 进入 `TRIAGE` 和 `COLLECTING_EVIDENCE`。
2. 请求模型生成严格 `tool_call`，总共收集 5 个只读证据。
3. 每个模型参数先经过 Pydantic，再进入 Tool Gateway 的第二次 Schema 校验。
4. 模拟器内部 `scenario_id` 在执行边界注入，不暴露给模型，也不写入模型参数审计字段。
5. 进入 `DIAGNOSING`，要求 `final_answer` 或 `proposed_action`。
6. Safety Guard 校验证据引用、风险等级和 Shell-like 内容。
7. 聚合所有请求的 input token、output token 和模型延迟到 `AgentRun`。
8. 按显式配置的单价计算 `estimated_cost`，并写入不含提示词正文的 `model_usage` 轨迹。

成功运行还会更新 `opspilot_model_estimated_cost_usd_total`。该值是配置单价下的估算，
不等同于服务商账单；自托管模型可保持单价为零，并单独核算 GPU 成本。

如果输出不是完整的严格 JSON，系统只允许一次修复请求。第二次仍非法就停止真实模型路径，
不会从 Markdown 或自然语言中提取隐式命令。

## 5. 安全降级

当 `OPSPILOT_MODEL_FALLBACK_TO_MOCK=true` 时，下列错误会降级到确定性 Mock：

- 模型请求超时、连接失败或非 2xx；
- 上游响应结构错误；
- 原始输出与单次修复输出都不合法；
- 推理/工具预算超限；
- 模型决策违反 Safety Guard。

轨迹首条会增加：

```json
{"event_type":"model_fallback","payload":{"reason":"ModelGatewayTimeoutError"}}
```

只记录异常类型，不记录 API key、请求正文或上游错误正文。关闭 fallback 后错误会向上抛出，
适合严格验收环境。工具自身的超时、重试和熔断仍由 `ToolResilience` 处理，不冒充模型故障。

## 6. 验证

无需启动真实模型即可运行：

```powershell
python -m pytest tests/unit/test_model_gateway.py
python -m pytest tests/unit/test_live_orchestrator.py
python -m pytest tests/unit/test_model_provider_switch.py
```

测试使用 `httpx.MockTransport` 和脚本化模型，覆盖请求参数、鉴权、token 统计、超时映射、
错误响应、完整证据循环、隐藏内部参数以及可审计降级。真实 GPU 联调和 TTFT/P50/P95
将在 Phase 3 后续可观测性里程碑记录。

连接真实服务后，可运行：

```powershell
python scripts/benchmark_http.py --requests 20 --concurrency 2 --completion-timeout 240 `
  > artifacts/phase3-live-benchmark.json
```

报告会从每个事件的 `model_usage` 轨迹汇总 input/output token、估算成本与模型延迟
P50/P95。`pricing_status=not_measured` 表示没有真实模型轨迹；`unpriced` 表示模型已运行但
单价仍为零。两者都不能把零成本解释成免费。
