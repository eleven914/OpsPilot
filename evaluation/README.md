# OpsPilot 离线评测协议

## 公平比较约束

Base、SFT、SFT+DPO 三组模型必须使用同一个 `sft_test.jsonl`、相同 temperature、相同最大输出 token 和相同工具定义。入口会先对照 Git 中版本化的数据清单检查测试文件 SHA-256；预测缺失、重复或多出样本时直接拒绝计分，避免替换考题或只提交“答得好的题”。

测试集当前仅含 `inventory` 服务，与训练集的 `gateway`、`order`、`payment` 以及验证集的 `notification` 隔离。合成数据尚未人工审核，因此报告只能验证评测流水线和记录实际输出，不能作为最终模型效果声明。

## 预测文件格式

每行一个 JSON 对象：

```json
{"sample_id":"sft:inventory_disk_pressure:0000:query_metrics","output":"{...模型的完整 JSON 输出...}","latency_ms":123.4,"input_tokens":512,"output_tokens":80}
```

其中 `sample_id` 必须完整覆盖测试集，`output` 必须保留模型原始输出，不允许评测前人工修正。token 和延迟字段可选。

## 指标定义

- Tool Selection Accuracy：单步工具题中，选中期望工具的比例。
- Argument Schema Match：单步工具题中，输出能通过该工具参数 Schema 的比例。
- Argument Exact Match：工具名和规范化参数都与答案一致的比例。
- Invalid Tool Call Rate：单步工具题中，未形成合法工具调用的比例。
- Unsafe Action Rate：直接把变更工具当只读工具调用，或变更建议违反 Safety Guard 的比例。
- Evidence Citation Precision：终局答案引用的证据中，属于题目已提供证据的比例。
- Task Success Rate：同一场景变体的五个工具步骤和一个终局步骤全部语义正确的比例。
- Average Tool Calls per Task：模型输出中工具调用数量除以场景任务数。
- Hallucination Rate：终局题中引用未知证据的比例；非法或不存在的工具也会在失败原因中标记。
- Valid Decision Rate：所有原始输出中，通过严格模型决策 Schema 的比例。

## 运行方式

先为三组模型分别生成预测文件。生成器会删除数据中最后一条 assistant
标准答案，只把 system 与 user 消息交给模型；每生成一条就写入 JSONL，远程运行中断后可用
`--resume` 继续：

```bash
python scripts/generate_predictions.py --output predictions/base.jsonl
python scripts/generate_predictions.py --adapter training/artifacts/qwen3-4b/opspilot-sft-v0.2 --output predictions/sft_v0.2.jsonl
python scripts/generate_predictions.py --adapter training/artifacts/qwen3-4b/opspilot-sft-v0.2-dpo --output predictions/sft_dpo_v0.2.jsonl
```

若某次生成中断，重复原命令并添加 `--resume`。已经存在输出文件时必须明确选择
`--resume` 或 `--overwrite`，避免静默覆盖真实预测。三组生成必须保持默认的
`temperature=0` 和 `max-new-tokens=1024`，才能通过公平比较门禁。

生成完成后运行相同计分入口：

```powershell
python scripts/run_evaluation.py --model-group base --model-name MODEL --model-version VERSION --predictions predictions/base.jsonl
python scripts/run_evaluation.py --model-group sft --model-name MODEL --model-version VERSION --predictions predictions/sft.jsonl
python scripts/run_evaluation.py --model-group sft_dpo --model-name MODEL --model-version VERSION --predictions predictions/sft_dpo.jsonl
```

报告默认写入 `evaluation/reports/generated/`。该目录不提交 Git，只有真实实验完成并经过审核后，才将冻结报告复制到版本化实验目录。

已审核的 v0.2 三组实测报告位于
[`reports/experiments/opspilot-synthetic-v0.2/`](reports/experiments/opspilot-synthetic-v0.2/)。
其中 `comparison.json` 已通过相同数据版本、测试文件 SHA-256、temperature 和最大输出 token
的公平比较门禁；详细解读与限制见
[`docs/PHASE2_EXPERIMENT_REPORT.md`](../docs/PHASE2_EXPERIMENT_REPORT.md)。

三组报告生成后，再通过比较门禁合并：

```powershell
python scripts/compare_evaluations.py evaluation/reports/generated/base.json evaluation/reports/generated/sft.json evaluation/reports/generated/sft_dpo.json
```

数据版本、测试文件哈希、temperature 或最大 token 任一不同，比较器都会拒绝输出对照结果。
