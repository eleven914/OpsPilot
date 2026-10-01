# OpsPilot QLoRA 训练流程

配置以 LlamaFactory `v0.9.5` 为兼容基线，基座模型通过 YAML 注入，默认是 `Qwen/Qwen3-4B-Instruct-2507`。正式 v0.2 SFT/DPO 已在 AutoDL RTX 4080 32GB 上运行；不可变实验清单和原始训练指标位于 [`experiments/opspilot-synthetic-v0.2/`](experiments/opspilot-synthetic-v0.2/)，完整解读见 [`docs/PHASE2_EXPERIMENT_REPORT.md`](../docs/PHASE2_EXPERIMENT_REPORT.md)。

## 1. 准备数据

```powershell
python scripts/generate_training_data.py
python scripts/prepare_llamafactory_data.py
```

第二条命令只导出 train 与 validation，不导出冻结 test，避免训练程序误读测试答案。转换结果在 `data/generated/llamafactory/`，其中 `dataset_info.json` 是 LlamaFactory 的数据注册表。

## 2. 安装独立训练环境

训练依赖 CUDA/PyTorch，建议在 E 盘的 WSL 或 Linux GPU 主机创建独立环境，不与 Web/API 运行环境混装：

```bash
uv venv /mnt/e/OpsPilotRuntime/llamafactory-venv --python 3.11
source /mnt/e/OpsPilotRuntime/llamafactory-venv/bin/activate
uv pip install "llamafactory==0.9.5"
```

## 3. SFT 与 DPO

```bash
python scripts/record_experiment.py --run-id qwen3-4b-sft-v0.2-001 --stage sft --model-name Qwen/Qwen3-4B-Instruct-2507 --config training/configs/sft/qwen3_4b_qlora.yaml --hardware "GPU型号与显存"
llamafactory-cli train training/configs/sft/qwen3_4b_qlora.yaml
python scripts/record_experiment.py --run-id qwen3-4b-dpo-v0.2-001 --stage dpo --model-name Qwen/Qwen3-4B-Instruct-2507 --config training/configs/dpo/qwen3_4b_qlora.yaml --hardware "GPU型号与显存"
llamafactory-cli train training/configs/dpo/qwen3_4b_qlora.yaml
```

上传到远程主机的源码归档通常不包含 `.git`。此时必须额外传入打包时记录的
`--git-commit COMMIT`；只有源码确实修改过时才同时传入 `--git-dirty`，不得用占位提交号。

记录命令会保存配置、原始数据与转换后训练文件的哈希、Git commit、随机种子、硬件和 worktree 是否干净。正式实验应在 `dirty: false` 时开始。SFT 先学习严格 JSON 与工具轨迹；DPO 再从 SFT adapter 继续优化安全偏好。两步都用 4-bit bitsandbytes 加载基座，但训练产物仍是 LoRA adapter。

`bf16: true` 要求支持 BF16 的 GPU；不支持时应根据硬件改为 `bf16: false`、`fp16: true`，并把实际配置记录进实验清单。显存不足时优先减小 `cutoff_len` 或增加梯度累积，不要悄悄改变测试集。

## 4. 合并导出

```bash
llamafactory-cli export training/configs/export/qwen3_4b_sft.yaml
llamafactory-cli export training/configs/export/qwen3_4b_sft_dpo.yaml
```

合并 LoRA 时必须加载完整精度基座，所以导出配置故意不含 `quantization_bit`。导出后的两组模型与原始 Base 模型再使用 `evaluation/README.md` 中的同一协议评测。

## 5. 已完成的 v0.2 实验

- SFT：3 epochs，1,008 个优化步骤，训练损失 `0.0258318440`，验证损失 `0.0000032358`，耗时 `14,069.93s`。
- DPO：3 epochs，255 个优化步骤，训练损失 `0.0003909359`，验证偏好准确率 `1.0`，奖励间隔 `13.2485781`，耗时 `5,176.42s`。
- 两个 LoRA adapter 均为 `132,187,888` bytes；权重没有提交 Git，而是保存在外部校验归档中。
- 冻结测试上的 Base/SFT/SFT+DPO 原始报告已版本化；这些结果来自未人工审核的合成数据，不能表述为生产准确率。
