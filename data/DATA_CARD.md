# OpsPilot Synthetic Dataset Card

## 状态

当前版本：`opspilot-synthetic-v0.2`

当前数据由 12 个自建故障场景程序化生成，并通过 Schema、安全策略、去重和泄漏检查。它尚未完成人工抽检，因此标记为 `rule_validated_not_human_reviewed`，不能作为最终模型效果基准。

v0.2 修复了首次 GPU 实验暴露的契约缺陷：模型输入现在包含公开工具 Schema、显式观察时间窗口、确定性的搜索词和候选变更信息；内部模拟器 `scenario_id` 不再作为需要模型猜测的参数。v0.1 清单和真实实验报告保留用于审计，但不得与 v0.2 报告直接比较。

## 数据组成

- 单步 Tool Calling：选择五个只读工具并生成合法参数。
- 多步故障轨迹：根据五份证据生成结论或审批动作。
- DPO 安全偏好：正确工具、合法参数、证据引用、强制审批和诚实表达不确定性。
- 每条模型输入包含完成标准答案所需的公开值，不依赖数据生成器内部公式。

默认生成规模：

- SFT：8,064 条；
- DPO：2,040 对；
- 独立 SFT 测试集：1,344 条。

## 切分与泄漏控制

以服务为不可拆分分组：

- train：gateway、order、payment；
- validation：notification；
- test：inventory。

同一服务的所有故障模板和改写只能出现在一个 split 中。验证器还会检查模板交集、ID 冲突和学习内容重复。

## 生成命令

```powershell
E:\OpsPilotRuntime\.venv\Scripts\python.exe scripts/generate_training_data.py
```

输出位于 `data/generated/`，包含六个 JSONL 文件和带 SHA-256 的 `manifest.json`。生成目录默认不提交 Git，避免大型派生数据污染源码历史。

## 已知限制

- 所有内容均为合成数据，不代表真实生产分布。
- 样本改写仍较模板化。
- 当前终局上下文提供规则生成的候选根因和动作，后续应替换为真实工具返回内容。
- test split 与 train split 服务隔离，但尚未经过独立人工审核。
- 在人工抽检、冻结版本和签署评测清单前，不得报告模型性能提升数字。
