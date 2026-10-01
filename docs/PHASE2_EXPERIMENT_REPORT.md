# Phase 2 训练与离线评测报告

## 1. 结论

OpsPilot Phase 2 已完成一次可复现的 QLoRA SFT、DPO 和 Base/SFT/SFT+DPO
三组公平评测。SFT 让 Qwen3-4B-Instruct-2507 在冻结的 v0.2 合成测试集上从
无法稳定输出严格工具决策，变为完整覆盖工具选择、参数生成和终局判断。DPO 在偏好验证集上
把全部 chosen 排在 rejected 之前，并且没有造成冻结工具测试回归。

这些数字只适用于当前规则验证、尚未人工审核的合成数据。它们证明训练与评测流水线可运行、
数据契约可学习，不是生产环境准确率，也不能替代人工金标、分布外测试和在线工程指标。

## 2. 可复现条件

| 项目 | 值 |
|---|---|
| 基座模型 | `Qwen/Qwen3-4B-Instruct-2507` |
| LlamaFactory | `0.9.5` |
| 硬件 | AutoDL RTX 4080 32GB |
| PyTorch / CUDA | `2.5.1+cu124` / `12.4` |
| 随机种子 | `20260925` |
| 源码提交 | `edf245f3b80a16fd3731e3ac7c4fae11c19215d1` |
| 源码状态 | clean |
| 数据版本 | `opspilot-synthetic-v0.2` |
| 冻结测试 SHA-256 | `fda58dfa185ccc23723c4c79eeb47cb863b57bf252e89245d50bd28994c9a3aa` |
| 推理参数 | `temperature=0.0`, `max_tokens=1024` |

训练使用 `gateway`、`order`、`payment`，验证使用 `notification`，测试只使用
`inventory`。服务和故障模板按 split 隔离，测试答案没有导出到 LlamaFactory 训练目录。

不可变实验清单：

- [`qwen3-4b-sft-v0.2-001.json`](../training/experiments/opspilot-synthetic-v0.2/qwen3-4b-sft-v0.2-001.json)
- [`qwen3-4b-dpo-v0.2-001.json`](../training/experiments/opspilot-synthetic-v0.2/qwen3-4b-dpo-v0.2-001.json)

## 3. 训练结果

### 3.1 SFT

| 项目 | 结果 |
|---|---:|
| 训练 / 验证样本 | 5,376 / 1,344 |
| epochs / optimization steps | 3 / 1,008 |
| 训练耗时 | 14,069.93s（约 3h54m） |
| train loss | 0.0258318440 |
| eval loss | 0.0000032358 |
| LoRA adapter 大小 | 132,187,888 bytes |

### 3.2 DPO

| 项目 | 结果 |
|---|---:|
| 训练 / 验证偏好对 | 1,360 / 340 |
| epochs / optimization steps | 3 / 255 |
| 训练耗时 | 5,176.42s（约 1h26m） |
| train loss | 0.0003909359 |
| eval preference accuracy | 1.0 |
| chosen reward | 6.8001618 |
| rejected reward | -6.4484162 |
| reward margin | 13.2485781 |
| LoRA adapter 大小 | 132,187,888 bytes |

原始训练指标位于 [`training/experiments/opspilot-synthetic-v0.2/`](../training/experiments/opspilot-synthetic-v0.2/)。

## 4. 三组公平评测

评测共包含 1,344 个样本、224 个任务，其中 1,120 个单步工具决策和 224 个终局决策。
公平比较器验证了三组报告的数据版本、测试哈希、温度和最大输出 token 完全一致。

| 指标 | Base | SFT | SFT+DPO |
|---|---:|---:|---:|
| Tool Selection Accuracy | 0.00% | 100.00% | 100.00% |
| Argument Schema Match | 0.00% | 100.00% | 100.00% |
| Argument Exact Match | 0.00% | 100.00% | 100.00% |
| Invalid Tool Call Rate | 100.00% | 0.00% | 0.00% |
| Unsafe Action Rate | 0.00% | 0.00% | 0.00% |
| Evidence Citation Precision | 100.00% | 100.00% | 100.00% |
| Task Success Rate | 0.00% | 100.00% | 100.00% |
| Average Tool Calls per Task | 0.0 | 5.0 | 5.0 |
| Hallucination Rate | 0.00% | 0.00% | 0.00% |
| Valid Decision Rate | 16.67% | 100.00% | 100.00% |

Base 的 1,232 个失败样本由 1,120 个 `invalid_decision` 和 112 个
`wrong_terminal_decision_type` 构成。SFT 和 SFT+DPO 都没有失败样本。

原始报告：

- [`base.json`](../evaluation/reports/experiments/opspilot-synthetic-v0.2/base.json)
- [`sft.json`](../evaluation/reports/experiments/opspilot-synthetic-v0.2/sft.json)
- [`sft_dpo.json`](../evaluation/reports/experiments/opspilot-synthetic-v0.2/sft_dpo.json)
- [`comparison.json`](../evaluation/reports/experiments/opspilot-synthetic-v0.2/comparison.json)

## 5. 如何解释结果

SFT 的主要收益是学习项目特有的严格 JSON 决策协议和完全可观察的工具参数契约。v0.1
曾要求模型猜测隐藏的 `scenario_id`、时间窗口和参数命名，导致评测失败；v0.2 将工具 Schema、
查询默认值和可观察上下文放入输入，并用生成期校验保证标准答案可从输入重建。

DPO 没有继续提高已经饱和的冻结工具测试，但偏好准确率达到 1.0，且三组门禁证明它没有让
SFT 能力回退。因此当前可以把 SFT+DPO 作为 Phase 3 的候选默认模型，同时保留 SFT adapter
作为消融基线。是否最终采用 DPO，要由人工安全集、分布外场景和在线指标共同决定。

## 6. 限制与下一步

- 合成数据仅通过规则验证，没有完成人工逐条审核，`eligible_for_final_benchmark=false`。
- 测试只覆盖 `inventory` 的两个故障模板，不能代表未知服务和自然语言噪声。
- 精确匹配指标适合验证契约，但不能单独衡量语义等价表达。
- 当前没有人工红队集、真实告警样本、TTFT、P50/P95、吞吐、成本或资源利用率数据。
- Phase 3 应接入模型服务，增加人工金标与扰动测试，并测量在线延迟、错误率、token、成本和资源占用。

## 7. 外部权重归档

权重未提交 Git。完整归档保存在开发者本机
`E:\OpsPilotArtifacts\OpsPilot-phase2-v0.2-results.tar.gz`：

| 项目 | SHA-256 |
|---|---|
| 完整结果归档 | `5F3F5A75911606F85453E0E21EEDA7D44DB84E24C587445DC0A9B7E4E94CD5F4` |
| SFT adapter | `48323591B64255A92BBBDE9E7DE68218FB8273846563898D1BEDDFE171A1C70B` |
| SFT+DPO adapter | `3CAF1C48D6ADE211F8F2D9A6F8C0463FBF991188BB540C145A840D28AD7541CE` |

归档中排除了重复 checkpoint，但保留最终 adapter、tokenizer 配置、训练指标、实验清单、
三组原始预测和评测报告。
