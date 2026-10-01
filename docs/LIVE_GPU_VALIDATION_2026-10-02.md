# OpsPilot 实机 GPU 服务验证与 HTTP 基线

记录日期：2026-10-02（Asia/Shanghai）。数据来自 AutoDL 容器中执行的 HTTP 基准脚本和 `nvidia-smi` 采样；原始文件保存在远端 `/root/autodl-tmp/OpsPilot/artifacts/`。下表是用户提供的终端输出的转录与计算结果。

## 环境与口径

- GPU：NVIDIA GeForce RTX 4080，显存总量 32,760 MiB。
- 推理服务：vLLM 0.30.0，`Qwen/Qwen3-4B-Instruct-2507` 基础模型，LoRA 模型别名 `opspilot-sft-dpo`，本机 `127.0.0.1:8000`。
- 应用服务：OpsPilot API，本机 `127.0.0.1:8010`；内联诊断；SQLite 数据库；真实模型调用，`OPSPILOT_MODEL_FALLBACK_TO_MOCK=false`，模型轮次上限 12。
- 测试请求：`inventory` 服务、P3、描述为 `inventory false alarm is healthy`。每个请求创建一条事件，等待状态进入 `RESOLVED`。
- 每组 4 个请求，HTTP 完成超时 240 秒。`duration_seconds` 是整组墙钟时间；每请求延迟在取得并发信号量后开始计时，因此不含信号量排队时间。吞吐为成功数除以整组时间。
- GPU 利用率、显存、功耗和温度用 `nvidia-smi` 约每秒采样一次。该采样包含测试开始及结束附近的时间，平均值不是仅限于模型计算阶段。

## 结果

| 并发 | 成功/请求 | 整组耗时 | 成功吞吐 | 相对串行加速 | 请求延迟 p50 / p95 | 模型输入 / 输出 tokens |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4/4 | 198.97 s | 0.0201 次/s | 1.00× | 50.08 / 55.09 s | 19,308 / 3,499 |
| 2 | 4/4 | 106.68 s | 0.0375 次/s | 1.87× | 52.37 / 53.40 s | 19,972 / 3,604 |
| 4 | 4/4 | 55.71 s | 0.0718 次/s | 3.57× | 53.30 / 55.63 s | 20,539 / 3,630 |

| 并发 | GPU 样本数 | GPU 利用率均值 / 峰值 | 显存占用 | 功耗均值 / 峰值 | 温度均值 / 峰值 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 200 | 26.61% / 47% | 27,822 MiB | 82.14 / 87.59 W | 39.01 / 43°C |
| 2 | 107 | 27.33% / 33% | 27,822 MiB | 78.17 / 84.46 W | 37.65 / 40°C |
| 4 | 56 | 28.73% / 55% | 27,822 MiB | 78.72 / 94.30 W | 36.93 / 39°C |

显存占用约为 27.17 GiB，占报告总显存的 84.9%。这是 vLLM 启动时预留的显存量，不应解读为每个并发请求额外占用 27.17 GiB。

## 功能与故障修复验证

- 独立真实事件：HTTP 201，`RESOLVED`，工具顺序为 `query_metrics → query_logs → get_service_info → search_runbook → search_incidents`，没有模型回退，模型用量 2,912 输入 / 588 输出 tokens，累计模型延迟 35.921 秒。
- 基准脚本原先固定 30 秒 HTTP 读取超时；真实请求约需 36–55 秒，导致客户端提前断开。已改为使用 `--completion-timeout` 设置读取超时，并在失败时返回非零退出码。
- 原实现会在等待模型时持续持有 SQLite 写事务，客户端超时后下一请求遇到 `database is locked`。已改为先提交事件状态，并在模型调用完成后写入诊断记录；并发集成测试及全部 261 项本地测试通过。
- 模型可能在取证和修复重试中超过原 8 轮预算；实机 API 已设置 `OPSPILOT_MAX_MODEL_TURNS=12`。所有上述 12 个基线请求成功完成。

## 结论与边界

在这一固定工作负载下，并发从 1 增至 4 后，整组完成时间从 198.97 秒降至 55.71 秒；12 个正式基线请求全部成功，且每请求 p95 延迟仍约 53–56 秒。这支持“并发 4 可运行”的工程结论，不能用于推断更高并发的容量、低故障概率或 p99 延迟。每档只有 4 个样本，p95 尤其不稳定；本轮未采集 CPU 和主机内存指标。

模型费用记录为 `pricing_status=unpriced`，估算值 0 美元仅表示未配置 token 单价，并非推理免费。SQLite 仍适合这次单机验证；若需要生产级并发写入与持久化，应另测 PostgreSQL 部署。当前服务是手动启动的，容器重启后需要恢复 `HF_HOME=/root/autodl-tmp/cache/huggingface`、vLLM 与 API；数据库位于 `/tmp`，需确认 AutoDL 的重启与清理策略后再用于长期保留。

## 远端原始文件

- 串行：`/root/autodl-tmp/OpsPilot/artifacts/live-baseline-c1.json`，`live-baseline-c1-gpu.csv`
- 并发 2：`/root/autodl-tmp/OpsPilot/artifacts/live-baseline-c2.json`，`live-baseline-c2-gpu.csv`
- 并发 4：`/root/autodl-tmp/OpsPilot/artifacts/live-http-c4.json`，`live-c4-gpu.csv`
- 独立真实事件：`/root/autodl-tmp/OpsPilot/artifacts/live-http-single-incident.json`
