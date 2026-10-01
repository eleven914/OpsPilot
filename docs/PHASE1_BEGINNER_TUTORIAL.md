# OpsPilot Phase 1 初学者教程：从诊断程序到安全处置 Agent

本文假设你掌握 Python 基础语法，但没有独立开发过包含 API、数据库、状态机、权限和浏览器测试的项目。

Phase 0 解决的是“系统能否跑通”。Phase 1 解决的是更难的问题：当 Agent 可以建议重启或回滚时，如何保证它不能越权、不能绕过审批、不能没有证据地执行动作，并且每一步都能审计。

## 1. Phase 1 的核心不变量

不变量是无论代码经过哪条分支都必须成立的规则。OpsPilot 的核心不变量包括：

1. 模型只能输出 `tool_call`、`proposed_action` 或 `final_answer`。
2. 未知工具和非法参数一定被拒绝。
3. 结论和动作必须引用真实存在的证据 ID。
4. 重启和回滚必须先产生审批记录。
5. 申请人不能审批自己的动作。
6. 变更只能调用预定义函数，不能执行 Shell。
7. 同一个幂等键不能造成重复变更。
8. 所有状态变化、消息、工具结果和审批结果都追加到轨迹，不能覆盖历史。

理解这些规则比记住某个 FastAPI 装饰器更重要。大型项目的可靠性来自跨模块共同维护的不变量。

## 2. 一次完整请求经过哪些层

```text
React / Alertmanager
        ↓
FastAPI 路由与身份校验
        ↓
Incident Service 创建 Agent Run
        ↓
显式状态机
        ↓
严格模型输出 Schema
        ↓
Safety Guard
        ↓
Tool Gateway
        ↓
证据、工具调用、审批、轨迹持久化
        ↓
SSE 推送给浏览器
```

路由不应该包含全部业务实现。路由负责 HTTP 协议，`opspilot/incidents/service.py` 负责运行诊断并持久化审计，Tool Gateway 负责工具边界。这样 Webhook、手工创建和补充消息可以复用同一套诊断逻辑。

## 3. 显式状态机

Agent 的主路径是：

```text
NEW → TRIAGE → COLLECTING_EVIDENCE → DIAGNOSING
                                         ├→ RESOLVED
                                         └→ PROPOSING_ACTION
                                              → WAITING_APPROVAL
                                              → EXECUTING
                                              → VERIFYING
                                              → RESOLVED
```

异常终态包括 `FAILED`、`REJECTED` 和 `NEEDS_HUMAN`。

`assert_transition()` 的意义是集中定义合法边。没有状态机时，不同接口可能直接把状态从 `NEW` 改成 `EXECUTING`，导致审批被绕过。状态机把业务规则变成可测试的代码。

## 4. 调用预算

一次运行最多允许：

- 8 次模型推理；
- 12 次工具调用；
- 180 秒运行时间。

预算在调用之前检查，而不是调用之后统计。否则第 13 次工具调用已经发生，限制就失去了意义。

预算可以防止模型循环、费用失控和故障服务被反复查询。

## 5. 严格模型 JSON

模型输出通过 Pydantic 联合类型校验。所有模型配置 `extra="forbid"`，因此未声明字段也会报错。

解析器只接受完整 JSON，不从以下文本中提取命令：

````text
建议执行：
```json
{"type": "tool_call", ...}
```
````

第一次失败时允许修复一次，第二次仍失败就抛出 `ModelOutputError`。修复不会跳过 Safety Guard 或审批。

## 6. Tool Gateway 为什么是安全边界

模型不能直接调用 Python 函数。它只能提交工具名和 JSON 参数，Tool Gateway 依次执行：

1. 检查工具是否在白名单；
2. 用 Pydantic 校验参数；
3. 区分只读工具和变更工具；
4. 应用超时、重试和熔断；
5. 对结果递归脱敏和裁剪；
6. 返回结构化结果供审计。

普通 `execute()` 调用变更工具会直接抛出 `ToolAuthorizationError`。只有审批路径能调用 `execute_approved_change()`。

## 7. 为什么读操作和写操作的重试不同

查询监控失败后再查一次通常不会改变系统状态，因此允许一次有限重试。

重启服务或回滚版本可能已经成功，只是响应丢失。如果直接重试，可能重复执行变更。因此写操作使用幂等键：相同键和相同请求返回第一次结果；相同键对应不同请求则被拒绝。

这就是命令与查询分离的实际价值。

## 8. 熔断器

某个工具连续失败达到阈值后，熔断器暂时打开：

```text
CLOSED ──连续失败──> OPEN ──冷却时间结束──> 再次尝试
```

熔断不是为了修好下游，而是为了避免持续请求已经故障的服务。每个工具独立计算熔断状态，日志故障不会阻止读取 CMDB。

## 9. 输出脱敏

Tool Gateway 会递归查找以下敏感内容：

- password、token、secret、api_key；
- Authorization Header；
- 文本中的 Bearer Token；
- `token=...` 等赋值形式。

脱敏位于工具出口，所以 Agent、数据库轨迹和前端默认都只能看到 `[REDACTED]`。

## 10. 证据模型

每次只读工具调用都会生成：

- `ToolCall`：工具、参数、结果、耗时、状态、幂等键；
- `Evidence`：来源 URI、观察时间、内容和 SHA-256；
- `TraceEvent`：供用户查看的追加式事件。

最终答案只能引用本次运行产生的证据 ID。Safety Guard 会拒绝不存在的证据引用。

## 11. 审批闭环

变更建议包含：

- 工具和参数；
- 风险等级；
- 证据 ID；
- 变更原因；
- 回滚方案；
- 过期时间。

审批通过后状态依次变为 `EXECUTING`、`VERIFYING`、`RESOLVED`。拒绝进入 `REJECTED`。超时未处理进入 `NEEDS_HUMAN`，绝不会默认批准。

数据库查询使用行锁意图和唯一约束，降低并发重复审批风险。

## 12. RBAC 与事件级授权

RBAC 回答“角色能做什么”：

- viewer：读取事件和审批；
- operator：创建和读取自己的事件；
- approver：查看并决定审批；
- admin：管理权限。

事件级授权回答“能操作哪条数据”。operator 读取他人的事件会得到 404，避免泄露事件是否存在。

当前项目通过请求头模拟身份。正式部署必须让可信认证代理覆盖这些请求头。

## 13. 12 类故障场景

场景不是散落在 `if/elif` 中，而是保存在 JSON 并通过 `ScenarioDefinition` 校验。每个场景包含：

- 指标序列；
- 日志片段；
- 服务拓扑；
- 正确根因；
- 推荐步骤；
- 禁止动作；
- 可接受替代路径；
- 可选的审批动作。

编排器先根据服务和描述选择 Scenario ID，之后五个只读工具都携带同一个 ID。这保证指标、日志和结论不会来自不同故障。

## 14. 事件消息

`POST /incidents/{id}/messages` 不会覆盖原始描述。它会：

1. 追加 `user_message` 轨迹；
2. 创建新的 `AgentRun`；
3. 使用补充信息重新诊断；
4. 把新证据继续追加到同一个事件。

审批或执行进行中时不允许开始新诊断，以免同时产生两个竞争动作。

## 15. Alertmanager Webhook

Webhook 使用独立 Token，不信任普通浏览器身份。它把 Alertmanager 标签映射为服务和严重级别，并使用 fingerprint 生成 `external_key`。

同一个 fingerprint 重复发送时返回已有事件，不会重复创建诊断和审批。这解决了告警系统常见的重复通知问题。

## 16. SSE 实时轨迹

浏览器请求 `/incidents/{id}/events?after=N`，服务端返回：

```text
id: 12
event: tool_result
data: {...}
```

`after` 支持断线后从最后序号继续。当前实现轮询数据库；后续异步架构可替换为 Redis 事件分发，而前端协议不需要改变。

## 17. 数据库迁移

Phase 1 增加了 Agent Run、Tool Call、Evidence、Approval 和外部事件幂等键。每次迁移都验证：

```text
upgrade head → downgrade base → upgrade head
```

仅验证“能升级”不够，因为开发和部署中也可能需要回滚。

## 18. 测试金字塔

- 单元测试：状态机、预算、Schema、Safety Guard、熔断和场景选择；
- 集成测试：真实 FastAPI、SQLAlchemy、审批、Webhook、消息与 SSE；
- 浏览器 E2E：Chromium 操作 React 页面，验证批准、拒绝和过期路径。

E2E 使用独立数据库和端口，不修改开发数据。Playwright 浏览器安装在 E 盘。

## 19. 推荐阅读顺序

1. `opspilot/agent/state.py`
2. `opspilot/agent/schemas.py`
3. `opspilot/agent/parser.py`
4. `opspilot/agent/policies.py`
5. `opspilot/tools/gateway.py`
6. `opspilot/tools/resilience.py`
7. `opspilot/incidents/service.py`
8. `apps/api/routes/incidents.py`
9. `apps/api/routes/approvals.py`
10. `apps/api/routes/webhooks.py`
11. `apps/web/src/App.tsx`
12. `apps/web/e2e/approval-flow.spec.ts`

## 20. 复习题与答案

### 问题 1：为什么不能让模型直接输出 Shell？

因为 Shell 的能力范围远大于业务动作，难以可靠校验目标、权限和副作用。预定义工具把能力限制在可验证的参数和固定实现内。

### 问题 2：为什么申请人不能审批自己的动作？

审批的价值来自第二个独立主体复核证据和风险。自审批会让审批退化为普通按钮。

### 问题 3：为什么重试查询通常安全，重试回滚却危险？

查询不改变系统；回滚可能第一次已经成功，只是响应丢失。再次执行会产生重复副作用，所以写操作需要幂等语义。

### 问题 4：为什么轨迹只追加不覆盖？

覆盖会破坏时间顺序和审计证据。追加式轨迹能回答谁在什么时间基于什么证据做了什么决定。

### 问题 5：为什么审批过期进入 `NEEDS_HUMAN` 而不是自动拒绝或批准？

自动批准违反安全原则；自动拒绝可能掩盖仍需处理的故障。`NEEDS_HUMAN` 明确表示系统无法安全继续，需要人工接管。

### 问题 6：Pydantic 校验和 mypy 有什么区别？

mypy 在开发阶段检查 Python 类型关系；Pydantic 在运行时校验来自模型、浏览器和 Webhook 的外部数据，两者不能互相替代。

### 问题 7：为什么 Webhook 需要幂等键？

Alertmanager 会重复发送仍在 firing 的告警。如果没有 fingerprint 幂等，相同故障会创建多个事件和审批动作。

### 问题 8：E2E 已通过是否意味着不需要单元测试？

不是。E2E 能证明主流程可用，但定位慢、组合有限。单元测试负责穷举状态转换和安全边界，E2E 负责证明各层真正连接起来。
