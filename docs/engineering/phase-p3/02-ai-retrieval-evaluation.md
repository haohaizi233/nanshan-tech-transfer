# Phase P3-4：AI 检索算法评测与优化报告

## 1. 算法基线与评测体系
- 现有基线（Baseline A）：`Heuristic Routing + LLM Intent Classification + Structured Query Plan + Hard Filters + Query Expansion + PostgreSQL Weighted ILIKE Retrieval + LLM Reranking + Preference Promotion + Grounded Explanation`。
- 评测体系（[nanshan-ai-agent/evaluation/](file:///d:/Users/Administrator/Desktop/南山小程序/nanshan-ai-agent/evaluation/)）：
  - 语料库：`datasets/corpus_v1.json`（含 8 条成果含草稿隐私样本 + 3 条需求）。
  - 调优集：`datasets/v1_dev.json`（12 条查询）。
  - 独立验收集：`datasets/v1_test.json`（12 条查询，调优与最终验收严格分离）。
  - 指标实现：[ir_metrics.py](file:///d:/Users/Administrator/Desktop/南山小程序/nanshan-ai-agent/evaluation/metrics/ir_metrics.py)、运行器：[run_eval.py](file:///d:/Users/Administrator/Desktop/南山小程序/nanshan-ai-agent/evaluation/runners/run_eval.py)。

## 2. 对照实验结果（Baseline A vs Candidate B）

### 2.1 Candidate B 优化内容
1. **领域同义词与分词归一**（[taxonomy.py](file:///d:/Users/Administrator/Desktop/南山小程序/nanshan-ai-agent/app/services/taxonomy.py)、[query_utils.py](file:///d:/Users/Administrator/Desktop/南山小程序/nanshan-ai-agent/app/services/query_utils.py)）：补充`计算机视觉`、`工业质检`、`AOI`、`新能源汽车`、`低空经济`、`遥感监测`等受控同义组与常见词表，保持 `MAX_EXPANDED_TERMS = 4` 上限。
2. **硬性条件确定性兜底**（[router.py](file:///d:/Users/Administrator/Desktop/南山小程序/nanshan-ai-agent/app/router.py)）：`apply_condition_guards()` 对未触发软偏好标记的显式金额上限/下限、需求合作方式（`detect_coop_modes`）和需求地域（深圳各区及主要城市）做确定性补齐，消除模型漏提导致的硬性条件违反。

### 2.2 独立验收集（`v1_test`）实测指标对比

| 指标 | Baseline A | Candidate B | 变化 |
|---|---:|---:|---|
| Intent Accuracy | 1.0000 | 1.0000 | 0.0000 |
| Constraint Extraction Accuracy | 0.7500 | 0.9167 | +0.1667 |
| Hard Constraint Violation Rate | 0.0000 | 0.0000 | 0.0000 |
| Recall@5 | 0.7500 | 0.9000 | +0.1500 |
| Recall@10 | 0.7500 | 0.9000 | +0.1500 |
| Precision@5 | 0.7333 | 0.8667 | +0.1334 |
| MRR | 0.8000 | 0.9000 | +0.1000 |
| NDCG@5 | 0.7917 | 0.8972 | +0.1055 |
| Zero-result Accuracy | 1.0000 | 1.0000 | 0.0000 |
| P95 Latency (ms) | 3.37 | 3.03 | -0.34 ms |
| LLM Calls / Query | 0.833 | 0.833 | 0.000 |

- 在调优集 `v1_dev` 上，Hard Constraint Violation Rate 从 `0.1667` 降至 `0.0000`，Recall@5 从 `0.9000` 升至 `0.9667`，NDCG@5 从 `0.9000` 升至 `0.9958`。
- 结论：**保留 Candidate B**；当前阶段无需为引入 Embedding/pgvector 增加额外延迟与维护成本（P3-4.6 原则）。
- `nanshan-ai-agent` 全量回归：**163 passed, 67 subtests passed**。
