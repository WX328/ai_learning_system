> GitHub精简快照说明（2026-10-26）：下文保留历史评测方法。rag_eval*.json及旧逐题报告因语料来源权利尚未确认，暂不分发；默认指向它们的RAG命令不能直接执行。请显式传入自有已授权数据集 --dataset；汇总结果见 [rag-public-summary.md](reports/rag-public-summary.md)。S2/S3合成数据、研究CLI和全部测试源码已保留，可独立运行。

# RAG 检索评测

S4 实际题库审核、数据关联诊断和主持式实验流程见 [S4_EXPERIMENT_PREPARATION.md](../S4_EXPERIMENT_PREPARATION.md)。复用 S3 策略与分析，演示题目默认未审，正式实验必须通过人工审核准入。

自适应学习 S3 评测另见 [S3_ADAPTIVE_EVALUATION.md](../S3_ADAPTIVE_EVALUATION.md)，包括时间顺序回放、三种规则比较、只读脱敏导出、固定/自适应学习实验 CLI 和论文图表。模拟规则结果与真实数据库历史分开报告；真实样本不足的指标标为不可评估。原有 RAG 评测入口不变。

默认评测集为 `rag_eval_100.json`，包含 100 道已标注的正例检索题。每道题标注一个或多个可以支撑回答的 `relevant_chunk_ids`。`rag_eval.json` 的原始 11 题和 `rag_eval_extended.json` 的旧 50 题保留用于历史对照。

## 100 题开发评测集（2026-10-23）

`rag_eval_100.json` 保留旧 50 题，新增 50 题，共 RAG 40 题、AI Agent 60 题，覆盖资料 21 和 24 的 34 个片段。题型包括精确术语 31 题、语义改写 16 题、代码/API 16 题、故障分析 12 题、执行流程 11 题、跨片段证据 9 题、质量评估 5 题。`notes` 说明标注依据；跨片段题列出需要结合的证据，完整重复的重叠正文也可能同时标注。

这是根据当前资料正文整理的开发集，尚未经独立人工复核。100 道题仍然来自两份资料，不等于 100 个独立主题；它不评估无答案拒答、最终生成答案或 Agent 完整任务成功率。Agent 文末的重复提问列表不作为答案证据；604 仅用于其开头的执行日志说明。数据集保存片段正文和向量的 SHA256 指纹，方便核对语料变化。

两个评测入口不指定 `--dataset` 时均使用这 100 题：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --dry-run
.\.venv\Scripts\python.exe scripts\compare_retrieval.py --dry-run --rerank
.\.venv\Scripts\python.exe scripts\compare_retrieval.py --rerank --top-k 10 --threshold 0.35 --rrf-k 60 --output evaluation\reports\retrieval-100-20261023.json
```

配对运行每题共享一次问题 Embedding，比较 `vector`、`bm25`、`hybrid`、`vector_rerank`、`hybrid_rerank` 五种配置。100 题正常完成时共 100 次问题向量化；两个非空候选集各重排一次，最多 200 次重排。重排按原始候选身份计算，不增加或截断候选。耗时不含答案生成，也不应作为独立端到端性能基准。详细结果和分组分析见 [100 题报告](reports/rag-public-summary.md)。再次运行请更换输出文件名。

历史评测集需显式指定：

```powershell
.\.venv\Scripts\python.exe scripts\compare_retrieval.py --dataset evaluation\rag_eval.json --dry-run
.\.venv\Scripts\python.exe scripts\compare_retrieval.py --dataset evaluation\rag_eval_extended.json --dry-run
```

## 标签校验与单配置评测

先核对或更新某份资料的分段：

```powershell
.\.venv\Scripts\python.exe scripts\list_rag_chunks.py --material-id 24
```

只校验评测集，不调用百炼：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --dry-run
```

执行真实检索评测。该命令会为每个问题调用一次当前配置的 Embedding API：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --output evaluation\reports\baseline.json
```

报告包含 Recall@1/3/5、Precision@1/3/5、截断到候选数量的 MRR（默认 MRR@10）、候选集召回率 `candidate_recall` 和平均检索耗时。`candidate_recall` 衡量最终候选中覆盖了多少已标注相关片段，默认相当于 Recall@10；重排保留相同候选，因此不会改变该指标。

仅更新同一批片段的向量未必改变 ID；重新切分或导入可能改变 ID。`--dry-run` 会检查标注 ID 是否存在并属于指定资料/知识点；若正文已改变，仍需人工核对标签。原始 11 题是初步标注集，不能代表整体质量。

## BM25 与混合检索

问答页通过 V2 `.env` 切换召回方式，修改后重启后端：

```dotenv
RAG_RETRIEVAL_METHOD=hybrid
RAG_RRF_K=60
RAG_RERANK_ENABLED=true
```

`vector`、`bm25`、`hybrid` 都可选择；未配置时保持 `vector`。BM25 索引在当前进程首次使用时建立，后续按资料正文复用缓存；上传、修改或删除导致片段集合变化后自动使用新索引。无需重建已有向量。该开关作用于资料问答，其他功能沿用原检索方式。

评测脚本的 `--retrieval` 独立选择召回方式，不受问答页的检索开关影响，默认 `vector` 保留旧基线：

| 方式 | 流程 | 模型调用 |
| --- | --- | --- |
| `vector` | 问题向量化 → 原向量排序 | 每题一次 Embedding |
| `bm25` | 中文分词与英文标识符提取 → BM25 关键词排序 | 本地召回，不调用 Embedding |
| `hybrid` | 同范围向量召回 + BM25 召回 → RRF 融合 | 每题一次 Embedding |

BM25 使用 jieba 处理中文，并保留 ASCII 标识符；得分采用 BM25 与正值 Lucene IDF。关键词在该范围内完全没有命中时，BM25 返回空结果；混合检索仍可使用向量结果。`similarity` 为 `null` 表示该候选没有向量分数，不能把它当成相似度 0。报告分别保留 `similarity`、`bm25_score`、`rrf_score`、`rerank_score` 和 `retrieval_methods`，这些分数的范围不同，不能直接相加或解释成答案正确概率。

RRF 仅融合两个排序列表的位置：每条片段的融合分为 `sum(1 / (rrf_k + rank))`，`rank` 从 1 开始。默认 `--rrf-k 60`；必须为正整数。向量相似度阈值只作用于向量分支，BM25 分支不会因相似度阈值被过滤。资料与知识点范围在两个分支中一致。

分别运行对照，保持题库、标签、向量阈值和最终候选预算一致。默认最终候选预算是 10，融合后的结果也最多保留 10 条，并非把两个分支的 10 条全部交给重排：

```powershell
cd <PROJECT_ROOT>
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --retrieval vector --top-k 10 --output evaluation\reports\vector.json
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --retrieval bm25 --top-k 10 --output evaluation\reports\bm25.json
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --retrieval hybrid --top-k 10 --rrf-k 60 --output evaluation\reports\hybrid.json
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --retrieval vector --top-k 10 --rerank --output evaluation\reports\vector-rerank.json
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --retrieval hybrid --top-k 10 --rrf-k 60 --rerank --output evaluation\reports\hybrid-rerank.json
```

每个命令是独立实验。`--rerank` 的 `baseline` 是该次运行中同一批候选的排序，适合严格比较重排前后；不同命令之间的网络耗时会波动。比较混合召回与向量召回时，先看 `candidate_recall`，再看 Recall@3、Precision@1、MRR@10 与总耗时。报告记录 `retrieval_method`、`rrf_k`、`tokenizer`、`top_k`、`similarity_threshold_scope` 和题库哈希，便于复现实验。

推荐用配对脚本一次比较三个召回方式，添加 `--rerank` 后还会比较两种重排结果：

```powershell
.\.venv\Scripts\python.exe scripts\compare_retrieval.py --dataset evaluation\rag_eval_extended.json --dry-run
.\.venv\Scripts\python.exe scripts\compare_retrieval.py --dataset evaluation\rag_eval_extended.json --rerank --output evaluation\reports\paired.json
```

配对脚本每题只向量化一次，三个方式共享同次数据库读取和问题向量，并保持最终候选上限相同。默认先预热每个资料/知识点范围的本地 BM25 索引，单独记录预热耗时；`--cold-index` 可关闭预热（同一进程中的后续查询仍可能命中缓存）。报告按各方式实际需要的检索组件计算延迟，重排调用各自实测；不计答案生成。五个方式不是五次独立的端到端性能测试，云端重排按模式依次执行，网络波动仍会影响比较。重排失败会停止，不会写入不完整报告，也不会覆盖历史报告。

计时覆盖实际检索调用（向量方式包含问题 Embedding），不包含答案生成。BM25 的首次分词器/索引初始化和后续缓存复用可能造成冷、热查询差异；重新启动的进程应视为冷运行。上述每个 CLI 命令启动新进程，不能把第二次命令当成索引已预热的查询。测稳定延迟时，需要在同一进程里先预热相同资料/知识点范围，再重复查询并记录运行顺序，分别报告首次查询、预热后的均值或 P95，不用一次 11 题的平均耗时声称稳定性能。

原 11 题中向量 Top10 已经覆盖全部标注相关片段，混合检索很难进一步提高该集的候选召回率。下一轮扩充人工标注题库，加入实际资料里出现的 `max_steps`、函数名、错误码、版本号等精确术语，以及术语的换种说法；先检查正文与片段 ID，再标注所有可以支撑答案的相关片段。资料中不存在的术语应单列为无答案测试，不能随意给它标注一个“相关片段”，也不能混入要求非空相关标签的召回率题库。保留独立验证集，避免反复调整参数只拟合这 11 题。

### 扩展开发验证集

`rag_eval_extended.json` 包含本次根据当前资料正文生成并标注的 50 道正例检索题：RAG 20 题、AI Agent 30 题，覆盖中文改写、英文术语、代码/API字段、执行流程、故障分析与质量评估。该集由实现助手依据资料快照生成，**尚未经独立人工复核，也不是独立留出的测试集**。结果用于开发阶段比较检索方案，不能据此声称已验证泛化性能。原 `rag_eval.json` 的 11 题没有改动，继续用于历史对照。

标签依据写在每题 `notes` 中；标签来自能支撑回答的讲解正文或代码，未将文末重复问题的测试列表标成答案。遇到答案跨切分边界时保留多个必要片段。两个相邻片段都包含完整支持答案的重叠正文时，可同时作为相关片段，计算召回率时会分别计数。扩展集的 Agent 评估题使用 603 的完整指标定义，未沿用旧集 604 仅有尾部内容的标签。`category` 是数据集中的描述字段，当前 `load_cases` 会丢弃它，因此常规报告不会自动给出分类指标。

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --dataset evaluation\rag_eval_extended.json --dry-run
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --dataset evaluation\rag_eval_extended.json --retrieval vector --rerank --top-k 10 --output evaluation\reports\extended-vector-rerank.json
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --dataset evaluation\rag_eval_extended.json --retrieval hybrid --rerank --top-k 10 --rrf-k 60 --output evaluation\reports\extended-hybrid-rerank.json
```

使用前需人工检查问题、标签和资料是否仍匹配；`--dry-run` 只能确认片段存在且范围正确，不能代替相关性复核。该扩展集未加入资料中没有出现的错误码或版本号，以免把不存在的内容错误标成正例。后续可用真实用户问题新增一个独立人工标注集，再判断默认检索方式和参数。

## 百炼 Reranker

使用 `qwen3-rerank` 的 HTTP API，官方说明：
https://help.aliyun.com/zh/model-studio/text-rerank-api

在 V2 的 `.env` 设置：

```dotenv
RAG_RERANK_ENABLED=true
DASHSCOPE_RERANK_MODEL=qwen3-rerank
DASHSCOPE_RERANK_TIMEOUT=15
```

默认使用现有 `DASHSCOPE_API_KEY`；需要独立密钥时设置 `DASHSCOPE_RERANK_API_KEY`。
若现有 Embedding 地址是业务空间域名（`*.maas.aliyuncs.com`），自动使用同一域名的
`/compatible-api/v1/reranks`。其他地址必须显式配置完整的 `DASHSCOPE_RERANK_URL`。
注意重排接口是 `compatible-api`，Embedding 接口通常是 `compatible-mode`。
模型必须在对应地域、业务空间可用；403/404 时核对模型权限和官方地址，不要盲目替换成 Embedding 地址。

问答开启后：按原资料/知识点范围以配置的检索方式召回候选 → 重排 → 取最多 3 条交给生成模型。资料片段不足或阈值过滤时，候选可能少于预算。
重排异常会记录 `RAG rerank fallback` 日志并使用召回阶段的原始排序；设置为 false 可关闭。
修改 `.env` 后重启 V2 后端。无需重新生成文档向量，无需在本地加载重排模型。
云端重排会发送问题和候选片段正文，新增一次 API 调用及对应延迟/用量。

## 同一批候选的前后对比

```powershell
cd <PROJECT_ROOT>
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --rerank --dry-run
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --rerank --output evaluation\reports\rerank.json
```

`--rerank` 显式开启评测重排，不受问答开关影响。不加该选项时评测 `--retrieval` 选择的原始排序（默认向量）。
每题只召回一次，再重排同一批候选。结果顶层是重排成绩，`baseline` 是这次运行同一批候选的原始成绩。
保留全部候选（默认 10 条）计算指标，不先截断到问答用的 3 条。原始 `similarity` 与 `rerank_score` 分开保存。
评测重排失败会以非零退出码中止，不回退冒充重排结果；不会覆盖已有报告，重复运行需换输出文件名。

分别记录检索耗时（包含问题 Embedding）、重排耗时和总耗时；未计算回答生成时间。
报告记录模型、向量维度、阈值、候选数量、题库哈希、每题排序和相关性分数。
保持候选数量、阈值和标签不变，重点比较 Precision@1、Recall@3/5、MRR@10 与总耗时。
重排无法找回候选集中没有的片段；分数不能与向量相似度直接比较。
一题若只标注 1 个相关片段，Precision@5 的上限就是 20%，不能仅凭该值判断质量差。
这些指标只测检索，未评估最终答案的正确性和忠实度。
