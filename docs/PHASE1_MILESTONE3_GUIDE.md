# Phase 1 里程碑 3：场景矩阵、严格模型输出与浏览器 E2E

这份文档解释本里程碑解决了什么问题、代码如何协作，以及初学者应重点理解的工程原则。

## 1. 为什么不能用“服务名”代表“故障”

同一个 `gateway` 服务可能发生 CPU 饱和、线程池耗尽或下游 5xx。如果代码只根据服务名返回一个固定根因，那么不同告警最终会拿到同一份指标和结论，这并不是诊断。

现在一次运行先执行以下选择：

```text
service + description
        ↓
关键词匹配 Scenario ID
        ↓
五个只读工具携带相同 Scenario ID
        ↓
指标、日志、拓扑、Runbook、历史事件来自同一场景
        ↓
生成最终答案或待审批动作
```

场景定义位于 `simulator/scenarios/scenarios.json`，每项都必须通过 `ScenarioDefinition` 校验。这样，错误或缺字段会在启动和测试阶段暴露，而不是运行到一半才出现 `KeyError`。

## 2. 12 类场景覆盖什么

| 故障类型 | 示例服务 | 默认处置 |
| --- | --- | --- |
| CPU 饱和 | gateway | 审批后重启单实例 |
| 内存泄漏 | notification | 审批后重启单实例 |
| 线程池耗尽 | gateway | 限流并排查阻塞下游 |
| 数据库连接池耗尽 | order | 查长事务，不盲目扩大连接池 |
| Redis 超时 | payment | 检查网络、延迟和连接池 |
| 下游依赖 5xx | gateway | 对故障下游降级 |
| 慢查询 | order | 保存执行计划并交 DBA 评审 |
| 磁盘空间不足 | inventory | 人工受控清理，禁止任意 Shell |
| 错误配置 | notification | 对比配置并人工修复 |
| 新版本发布回归 | order | 审批后回滚版本 |
| 单实例异常 | inventory | 审批后重启故障实例 |
| 告警误报 | payment | 交叉验证后关闭误报 |

不是所有故障都应该自动产生变更动作。例如，慢查询可能需要新增索引，但自动执行 DDL 超出了 MVP 的安全边界，所以这里只给出证据和人工步骤。

## 3. 为什么模型输出必须是严格 JSON

大语言模型可能输出以下内容：

````text
我建议执行下面的命令：
```json
{"type": "tool_call", ...}
```
````

如果程序从任意文本中搜索 JSON 或命令，就可能把日志、Runbook 或攻击者输入误当成真实操作。因此 `parse_model_decision()` 只接受完整 JSON，并通过 Pydantic 联合类型验证为以下三类之一：

- `tool_call`
- `proposed_action`
- `final_answer`

所有模型都设置了 `extra="forbid"`。即使主要字段合法，只要混入未定义的 `command` 字段，也会被拒绝。

## 4. “最多一次修复”是什么意思

模型第一次返回 JSON 语法错误时，调用方可以把原输出和校验错误交给修复器一次。修复后的结果必须重新执行完整 Schema 校验。

```text
第一次输出
  ├─ 合法 → 接受
  └─ 非法 → 修复一次
                ├─ 合法 → 接受
                └─ 非法 → ModelOutputError
```

限制为一次可以避免模型陷入无限修复循环，也能使模型调用预算可预测。修复只负责格式，不会跳过 Safety Guard、证据校验或审批。

## 5. 事件级授权

RBAC 解决“角色能做什么”，事件级授权解决“这个角色能操作哪一条数据”。当前规则是：

- operator 只能读取自己创建的事件；
- viewer 可以跨事件查看审计信息；
- approver 可以查看待审批事件；
- admin 拥有管理权限。

其他 operator 请求不属于自己的事件时，API 返回 404 而不是 403。这样不会向调用者确认某个事件 ID 是否真实存在。

当前身份来自演示请求头。正式部署时，这些请求头必须由可信认证代理覆盖，不能直接信任浏览器自报身份。

## 6. E2E 测试与普通单元测试的区别

单元测试可以证明场景选择函数正确，但不能证明用户真的能在页面完成审批。Playwright E2E 会实际启动：

```text
Chromium → Vite/React → FastAPI → SQLite/Alembic → Agent/Tool Gateway
```

测试执行以下动作：

1. 打开 OpsPilot 页面；
2. 填写 gateway CPU 告警；
3. 等待状态进入 `WAITING_APPROVAL`；
4. 检查动作和风险等级；
5. 点击“批准并执行”；
6. 验证 `tool_result`、`verification` 和 `RESOLVED`。

E2E 使用独立端口和独立数据库，不会修改开发数据库。浏览器安装目录通过 `PLAYWRIGHT_BROWSERS_PATH` 指向 E 盘。

## 7. 本里程碑的测试策略

- 每个场景必须通过 Pydantic Schema；
- 12 个场景 ID 和故障类型不能重复或遗漏；
- 每个场景的关键词必须能选中对应 Scenario ID；
- 五次工具调用必须引用同一个 Scenario ID；
- 无动作场景必须输出匹配的根因；
- 有动作场景必须进入 `WAITING_APPROVAL`；
- 非法 JSON、未知工具、多余字段和 Markdown 包裹输出必须被拒绝；
- 不属于事件的 operator 不能读取详情或 SSE；
- 最终浏览器 E2E 必须真实完成审批闭环。

## 8. 建议阅读顺序

1. `opspilot/tools/scenarios.py`
2. `simulator/scenarios/scenarios.json`
3. `opspilot/tools/gateway.py`
4. `opspilot/agent/orchestrator.py`
5. `opspilot/agent/parser.py`
6. `tests/unit/test_scenarios.py`
7. `tests/unit/test_model_parser.py`
8. `apps/web/e2e/approval-flow.spec.ts`

阅读时重点观察：外部数据先校验、所有证据保持同一场景上下文、模型输出不能绕过安全策略、最终用用户视角验证完整链路。
