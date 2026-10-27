# S3：自适应学习算法评估与小规模实验

后续 S4 的实际题干、逐题审核和主持式操作见 [S4_EXPERIMENT_PREPARATION.md](S4_EXPERIMENT_PREPARATION.md)。S3 元数据示例仍适用于 synthetic_experiment；新 real_experiment 计划必须使用 S4 完整、人工审核通过的实际题库，不能再仅凭手填哈希启动。

## 已有代码与数据能回答什么

S2 的 `assess_topic` 是纯函数，`explain_difficulty` 和 `mastery_priority` 可直接复用。原 `scripts/evaluate_mastery.py` 比较固定序列的最终快照，适合规则案例验证，但没有逐时刻预测、未来结果标签或实验分组。本阶段保留该脚本，独立增加回放与实验工具，不修改生产服务、接口、默认 `rules_v2`、JWT、RAG、管理员、XP、成就或教练行为。

2026-10-23 只读检查和导出时，现有库有 51 条首次答题、5 条复习；只有 10 条可归因到有效且属于答题用户的知识点，覆盖 2 个账户、5 个用户知识点。46 条记录因缺少知识点或无效归属/关联被排除。未向任何知识点强行补齐旧题关联，未修改或迁移正式库；导出前后数据库字节 SHA256 一致。

这里的“真实历史”指真实数据库里既有的记录，不能确认每条都来自独立人类测试者，也不是受控实验。满足至少三道同知识点历史题的预测目标仅 2 个，来自 1 个账户；真实预测、排序和趋势指标均**不可评估**，没有编造准确率、显著性或学习收益。

当前库没有前测/学习/后测标签、固定/自适应分组，也没有完整的历史推荐、待答题状态和策略版本日志。Topic 的时间默认值也不足以重建历史目录，因此正式库导出采用“首次观察到该知识点答题时才纳入目录”的保守规则，不能复原当时尚未练习的知识点。

## 离线回放口径

入口为 `scripts/evaluate_adaptive.py`，核心在 `evaluation/adaptive_replay.py`。输入只包含脱敏标识、时间、首次/复习类型、正误和题目难度；不需要题干、答案文本、学习资料、对话或账号凭据。

三种算法始终看到相同的已发生历史、题目难度和目录：

| 算法版本 | 掌握度指数 | 难度规则 |
| --- | --- | --- |
| `raw_accuracy_v1` | 全部不同题目的首次正确率 ×100 | 用全部首次正确率，≥80%升一档、<50%降一档 |
| `recent5_accuracy_v1` | 最近最多五道不同题目的首次正确率 ×100 | 用同一最近窗口，无三题升档门槛 |
| `rules_v2` | 直接调用现有 S2：难度权重、平滑、历史70%+最近30%、有限复习证据 | 直接调用生产 `explain_difficulty`，升档至少三道题 |

两条基线特意只使用首次答案，区别于 S2 报告里“最新复习覆盖首次结果”的历史旧实现；本阶段名称和版本独立，避免把不同基线混为一谈。三者使用同一个生产 `mastery_priority`：已练且低于80 → 未知 → 达标，再按分数、样本数、标识排序。脱敏导出的同分顺序使用不透明 topic ID，因此可能与生产数字 ID 的同分顺序不同；主要评分与难度规则一致。

严格按 UTC 时间升序回放，原 SQLite 无时区值按系统既有约定解释为 UTC：

1. 到达时间 `t`，仅使用 `<t` 的答题和复习。
2. 冻结 `t` 的所有首次新题预测、知识点排序和难度建议；**同一时间戳的答案不能互相提供信息**。
3. 揭晓该批首次结果，再纳入有效复习；只供之后的时间使用。
4. 每个用户、每题仅最早首次记录计入样本，后续重复首次提交统计为忽略；孤立或过早复习忽略。每题最新复习的有限证据由 S2 自己处理。
5. 全部预测完成后，单独用后续结果计算评估指标。未来结果不会反馈评分器。

新题的实际难度/正误不会预先进入该知识点历史。评分期间不读取最终 `TopicMastery` 缓存。历史日志的题目动作固定，不把某算法推荐后未实际发生的答案模拟成真实反事实结果，也不复原缺失的待答题状态。

### 指标与不可评估条件

- **后续结果预测**：在每道首次新题答案揭晓前，以该知识点指数/100作为未校准分数代理，报告 Brier 与 AUC。S2 指数不是能力概率；Brier 不能称为已经校准的概率准确率。只纳入已有至少三道不同题目的目标，冷启动不填0或50%。
- **知识点排序**：每个冻结决策之后、严格晚于该时间的最多10道实际首次答题中，每个候选知识点至少有两道未来题，才用未来正确率比较两项知识点的排序。低分应对应较低未来正确率；未来正确率相同的比较排除，预测同分计0.5。统计单位是“决策时刻的知识点对”，窗口重叠，绝非独立测试者数量。
- **近期趋势响应**：对同知识点相邻、不重叠的五题块，实际正确率变化至少20个百分点时，检查指数变化方向是否一致，同时保存改善/退步各自的分数变化均值。这是对已观察表现的规则响应，不能当作真实能力变化识别准确率。
- **少样本稳定性**：前四题评分快照的0/100极端分占比、相邻快照平均绝对跳变，以及历史少于三题时的升档次数/决策数。更平滑不是学习更有效的证据。
- **难度动作**：升档、降档、保持、越界次数；没有“最优难度”标签，不虚构推荐准确率。各算法都以该知识点最后实际答题难度为基准，限制1～5。

默认统一数量门槛为20个相应观测，且来自至少2个学习者；预测、排序、趋势不足时输出 `null` 和 `not_evaluable`，保留真实分母和原因。AUC另需正确和错误两类结果。该门槛只是报告门槛，不是统计功效证明，20个高度相关时刻也不等于20个独立样本。少样本稳定性和难度动作仅给描述计数，分母为0时不填数值。

报告记录输入数据 SHA256、算法版本、三份实现文件 SHA256、配置、CSV 指纹及运行环境。图表核对 CSV 指纹，防止混用另一数据集的决策表；重复运行同一输入/实现/配置的核心 JSON、Markdown、CSV 内容一致。

## 运行离线评估

在 V2 项目根目录运行。所有 CLI 都通过 `python -m` 调用，避免 Windows 脚本导入路径歧义。

### 规则案例：明确的合成数据

```powershell
.\.venv\Scripts\python.exe -m scripts.generate_adaptive_fixture --output evaluation/adaptive_s3_synthetic.json
.\.venv\Scripts\python.exe -m scripts.evaluate_adaptive --dataset evaluation/adaptive_s3_synthetic.json --output-dir evaluation/reports/adaptive-s3-synthetic
```

数据为8个脚本学习者、24个用户知识点、480道首次题、32次复习。结果序列预先固定，包含改善、退步、再次转向和混合表现；答案不由推荐策略生成，不是已验证的人类学习模拟器。重复序列不能增加真实实验样本量。

### 真实历史：显式选择数据库，只读导出

```powershell
.\.venv\Scripts\python.exe -m scripts.export_learning_history --database learning.db --output .evaluation-private/s3-new/history.json
.\.venv\Scripts\python.exe -m scripts.evaluate_adaptive --dataset .evaluation-private/s3-new/history.json --output-dir .evaluation-private/s3-new/replay
```

可重复传 `--user-id 1 --user-id 2` 限定用户；SQL参数绑定且再次校验资料所属用户、知识点和资料关联。未提供数据库路径不会自动访问生产库。导出器使用 SQLite `mode=ro`、`query_only=ON` 和单个快照事务，不创建缺失数据库，不写缓存，不调用模型。已有导出文件拒绝覆盖。

默认每次导出随机生成内存 HMAC 密钥，无法跨导出关联；对同一已保存数据集仍能完全重放。确需跨批次稳定标识时，使用 `--pseudonym-key-file 私有文件路径` 提供至少32字节的随机密钥，密钥不要入库、提交或分享。导出保留题目/资料/用户的关联和时间，**属于假名化而非匿名化**。`.evaluation-private/` 已加入 Git 忽略；这不是操作系统访问控制，仍需妥善保管。

本次提交的真实历史报告只含聚合统计和不显示标识的图表；原始脱敏事件与逐决策 CSV 保存在 `.evaluation-private/s3/`，不放入可提交报告目录。生产库如继续答题，再导出会得到不同数据指纹和结果，论文应保留实际使用的冻结数据集。

## 小规模学习实验：无需改生产页面

提供研究者主持的本地 CLI。题目由研究者事先准备并人工审查，通过 `item_id` 对照独立题册；不临时调用AI出题，不经过生产XP或答题表。题库JSON只存元数据，**示例没有真实题干，不能直接用作真实前后测**。

### 建议流程

1. 招募同意参与的测试者，仅分配研究编号；另行私密保存身份对应关系。先确定主要指标、题目、题数、停止条件和分配种子，再收集结果，避免看结果后挑指标。
2. 准备 A/B 两套前后测平行卷和独立学习题池。A/B 的知识点×难度题数必须相等；题目 ID、内容指纹、近似题家族不能跨卷或学习阶段复用。哈希/家族由研究者填写；软件不能证明题目等价或自动识别未正确标注的近似题，仍需人工复核。
3. 预设固定/自适应两组和 A→B/B→A 的组合，固定种子随机分块分配。完整四人块同时平衡模式及卷顺序；尾部不足四人可能不完全平衡，最终报告所有分组和退出数量。
4. 前测不反馈答案。学习默认12道不同题；两组使用同一个 S2 知识点优先级，固定组始终指定难度2，自适应组使用 S2 难度策略，初始也为2。前后测答案不进入学习阶段算法状态。题池每知识点需覆盖1～5级，并有足够固定难度题目。
5. 自适应题池若耗尽指定难度，选择最近可用难度，同距取较低，记录请求/实际难度和偏离原因；固定组不切换难度。记录每题正误、UTC时间、可选用时和决策指纹；每人阶段按前测→学习→后测推进，禁止重复题和旧决策重放。
6. 完成后测后再反馈和访谈。比较完整参与者的前测、后测和增量，同时披露未开始、未完成、题池偏离和分组基线。题数相同而用时可能不同，可记录用时帮助解释。参与者疲劳或退出时保留缺失，不编造剩余答案。

两组共用选点规则并不保证实际知识点顺序一样：难度改变作答表现后，后续选点也可能不同。这是策略的间接影响，应在实验讨论中披露。

### 实际命令

先创建一个**空的模拟流程**练习 CLI，换一个尚不存在的输出目录：

```powershell
.\.venv\Scripts\python.exe -m scripts.create_experiment_example --output-dir .evaluation-private/s3-demo
.\.venv\Scripts\python.exe -m scripts.learning_experiment next --plan .evaluation-private/s3-demo/plan.json --records .evaluation-private/s3-demo/records.csv --participant DEMO-P01 --output .evaluation-private/s3-demo/decision.json
```

`next` 只返回下一题元数据，不包含答案。给测试者展示对应题册题目，真实判分后再记录，例如：

```powershell
.\.venv\Scripts\python.exe -m scripts.learning_experiment record --plan .evaluation-private/s3-demo/plan.json --records .evaluation-private/s3-demo/records.csv --decision .evaluation-private/s3-demo/decision.json --correct 1 --duration-seconds 30
```

`--correct` 必须填写实际判分0/1，示例命令不是已发生的观察。继续 `next` / `record`，系统自动推进阶段。旧决策、重复请求、跳阶段、错误题号、非递增时间和被更改的计划会拒绝；记录写入使用独占锁与临时文件替换。此工具按可信研究主持人单点录入设计，不是带鉴权的多人后台，也不能防止主持人篡改所有原始文件。崩溃后的 `.lock/.tmp` 需先检查和备份再处理。

真实实验需先以人工复核的题库元数据替换示例，用研究编号JSON数组创建计划，明确数据来源：

```powershell
.\.venv\Scripts\python.exe -m scripts.learning_experiment plan --bank 私有题库元数据.json --participants 研究编号.json --source real_experiment --learning-steps 12 --fixed-difficulty 2 --seed 20261023 --output-dir .evaluation-private/real-study-01
.\.venv\Scripts\python.exe -m scripts.learning_experiment analyze --plan .evaluation-private/real-study-01/plan.json --records .evaluation-private/real-study-01/records.csv --output-dir .evaluation-private/real-study-01/report
```

分析输出 JSON、Markdown 和逐参与者 CSV。主要结果是 `post_correct_fraction - pre_correct_fraction`，不是掌握度指数的变化。完整参与者不足每组5人时，组间增量差与区间标为不可评估；组内已完成者均值仍可作小样本描述并同时披露分母。达到门槛时给出参与者级2000次固定种子 bootstrap 探索区间，不把题目当作独立参与者，也不自动宣称显著提升。默认五人门槛不是正式功效分析；小样本区间仍不稳定，不能代替前测平衡、卷等价、缺失与混杂分析。

已保存的 `evaluation/examples/s3-experiment/` 是8个模拟研究编号的**空记录**示例，完整实验观察为0，真实前后测收益尚不可评估。

## 论文图表

Matplotlib 仅为评估绘图的可选依赖，未加入生产运行依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r evaluation/requirements.txt
.\.venv\Scripts\python.exe -m scripts.plot_adaptive_evaluation --report-dir evaluation/reports/adaptive-s3-synthetic --output-dir evaluation/reports/adaptive-s3-synthetic/figures --experiment-report evaluation/examples/s3-experiment/report/experiment.json
.\.venv\Scripts\python.exe -m scripts.plot_adaptive_evaluation --report-dir .evaluation-private/s3/replay --output-dir evaluation/reports/adaptive-s3-real-history/figures
```

本次 Windows / Python 3.13 的精确绘图包版本保存在 `evaluation/requirements.lock`；需要重现绘图环境时可改用 `pip install -r evaluation/requirements.lock`。当前绘图版本为 Matplotlib 3.11.2，数值评估本身不依赖 Matplotlib。

每张图同时保存向量 PDF、可编辑 SVG 和300dpi PNG：掌握度轨迹、相同日志下的推荐难度轨迹、算法指标比较、实际样本量，以及可选实验完成数量/增量可用性。轨迹是一个实际观察到的用户知识点，不把不同人的时间轴强行平均。图表使用英文科学标注以避免中文字体依赖，中文解释见报告。

每图标注数据来源、`adaptive_eval_v1`、`rules_v2`、数据指纹和相关性限制；实验图使用它自己的来源，避免误用离线合成数据标签。缺失指标显示 `N/A`，不画成0高度柱。`figures.json` 保存完整指纹、配置和 Matplotlib 版本。

## 本次结果与分析

[模拟规则回放报告](evaluation/reports/adaptive-s3-synthetic/report.md)、[真实库历史报告](evaluation/reports/adaptive-s3-real-history/report.md) 与 [空实验报告](evaluation/examples/s3-experiment/report/experiment.md) 分开保存。

在**预设合成序列**的408个共同预测目标上，历史正确率、最近五题、S2的 score-proxy Brier 分别为0.3097、0.2568、0.2730；AUC分别为0.3611、0.6512、0.5219。S2优于长期正确率基线，但在这些反转序列上不及最近五题规则，不能只展示有利指标。知识点对排序一致性分别为0.2914、0.4570、0.3833，存在1208个相关窗口比较；三种规则在32个明显的五题块趋势变化中均同向响应。

前四题评分的96个快照中，两条正确率基线的极端分占比为75%，S2为0%；平均绝对分数跳变9.259→7.722。少于三题的48个决策中，两条基线各升档21次，S2为0次。它们只说明规则响应和小样本约束达到设计预期，不构成学习效果证据。

真实库仅2个合格预测目标、0个合格排序比较和0个趋势窗口，不能报告可靠的预测性能；没有完成的真实实验参与者，无法报告前后测收益。后续优先补齐真实实验数据和题目难度/卷等价审查，不因本次离线结果修改生产权重。

## 自动化测试与边界

新增 `test_adaptive_evaluation.py`、`test_learning_experiment.py`、`test_adaptive_figures.py`，覆盖时间泄露、同刻答案/复习、未来目录、去重、孤立复习、时区、手算指标、样本门槛、排序标签、重复执行、只读导出、跨用户/资料、CSV指纹、来源标签、题集重叠、两种模式、分配复现、阶段推进、重复录入、锁、缺失、增量与参与者级区间。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Get-ChildItem tests/frontend*.mjs | ForEach-Object {
  node --experimental-vm-modules $_.FullName
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

本次实际执行完整后端回归：**210项通过，0失败，0跳过，65.637秒**；其中 S3 新增35项（回放/导出19、实验14、绘图2）。测试使用独立临时数据库和本地替身，不向真实学习库写入，不调用付费模型。前端五个既有脚本全部通过，仍有既有 Node VM Modules 实验功能及教练测试监听器数量提示，未忽略失败断言。Ruff检查通过；Git差异检查只有已有换行格式提示。

九张图（模拟五张、真实库历史四张）均已实际生成 PDF/SVG/PNG，缺失数据不画成0分。图表的最后布局修正另行运行两项绘图测试验证。完整结果见 `evaluation/reports/adaptive-s3-verification.json`。

### 文件清单

- 离线核心：`evaluation/adaptive_replay.py`。
- 实验核心：`evaluation/learning_experiment.py`。
- CLI：`scripts/export_learning_history.py`、`scripts/evaluate_adaptive.py`、`scripts/generate_adaptive_fixture.py`、`scripts/learning_experiment.py`、`scripts/create_experiment_example.py`、`scripts/plot_adaptive_evaluation.py`。
- 输入与结果：`evaluation/adaptive_s3_synthetic.json`、`evaluation/examples/s3-experiment/`、`evaluation/reports/adaptive-s3-synthetic/`、`evaluation/reports/adaptive-s3-real-history/`。
- 测试：上述三个新增测试文件；原功能测试未改动。
- 配置/说明：`evaluation/requirements.txt`、`evaluation/requirements.lock`、`.gitignore`、本文件及 `evaluation/README.md` 的入口链接。

限制还包括：题目难度只取现有静态标注，没有历史版本；相同内容但不同ID的旧题无法自动去重；未来窗口反映已选题目的表现，受选题偏差和难度影响；全局AUC混合不同用户与难度，非个体校准结果；数据很多时当前逐时刻全历史计算需要增量优化。没有训练模型、遗忘曲线或因果策略估计，也没有将模拟结果当成真实学习效果。
