# S4：真实学习实验准备与数据质量

本阶段复用 S3 的随机分配、时间顺序决策、rules_v2、记录校验及分析。不回填正式库，不改变生产算法参数。实验使用独立文件，不经过生产用户、XP、成就或模型接口，无需新服务或框架。

## 数据关联诊断

2026-10-23 的只读审计见 `evaluation/reports/data-quality-s4.json`。每条记录按首个不满足条件分类，不猜测 NULL 题的归属。

| 对象 | 总数 | 知识点为空 | 有效关联 |
| --- | ---: | ---: | ---: |
| questions | 55 | 36 | 19 |
| 首次答题 | 51 | 41 | 10 |
| 错题复习 | 5 | 5 | 0 |

未检出缺失题目、缺失资料、无效所有权、悬空知识点、跨资料关联或资料内重复知识点名称。S3 的 46 条排除记录可确认为题目 `topic_id IS NULL`，不能解释成表现差或正确率 0%。审计前后数据库 SHA256 一致：`REDACTED_PRIVATE_DATABASE_SHA256`。

| 环节 | 诊断及最小修复 |
| --- | --- |
| 资料解析 | 保存带所属用户的 LearningMaterial；尚未提取知识点不是解析失败，没有发现解析清除题目关联的证据。 |
| 分块与提取 | LearningChunk.topic_id 可为空，同一短片段可能涉及多个知识点。检索回退到同一资料时，应保留出题所选的逻辑知识点，不能把片段 NULL 当成题目 NULL。 |
| 知识点保存 | 原 save_topics 清空片段关联、删除重建 Topic，存在破坏稳定 ID 的潜在风险；当前未发现相应悬空记录，不能声称它造成了本次缺失。现在已有目录直接复用，不重新编号，不再次调用提取/分配模型；首次保存先验证空名、重名和长度。 |
| 普通出题 | 前端/API 允许自由主题且省略 topic_id，服务按文本检索，保存器原样写入 NULL，是可复现的当前缺口。现在必须先提取并选择有效知识点，缺失时在模型/Embedding 调用前返回 400。 |
| 教练出题 | PracticeArgs 原允许省略 ID，即便 is_adaptive=True 也可能保存 NULL。现在工具 schema 要求使用当前资料学习档案内的 ID。 |
| 生成/保存 | 生成服务核对资料所有权和知识点归属；保存服务再次拒绝 NULL、无效及跨资料 ID。文本主题不会被猜测为数据库 ID。普通、自适应及教练仍共用保存服务。 |
| 答题与评估 | 答题/复习通过 question_id 继承关联，并非提交时丢失 topic_id。旧 NULL 题保留答题、XP 和反馈能力，仍不纳入知识点评估；首次提交遇到无效非空关联时在写答案/发 XP 前返回 409。 |
| 时间 | Question/Topic 原默认值在模块导入时求值，改为逐条创建时求值。旧时间不修正，S3 仍采用首次观察知识点的保守历史目录口径。 |

缺少历史生成入口和参数日志，无法逐题确认当时来自哪个入口、旧版本或维护脚本；不能从 is_adaptive 单独判断。本次没有修改历史题、答题、关联、时间或掌握度缓存。

复查命令（输出文件需不存在）：

```powershell
cd <PROJECT_ROOT>
.\.venv\Scripts\python.exe -m scripts.audit_learning_links --database learning.db --output .evaluation-private/s4-check/links.json
```

审计使用 SQLite mode=ro、query_only 和单一快照，仅输出聚合数量，没有 repair/backfill 模式。正式应用并发写入可能使文件哈希变化，应区分外部变更。

## 实际题库与审核

`evaluation/examples/review-bank-s4/` 包含 28 道实际 Python 列表/字典选择题及审题册：A/B 各 4 题、学习题 20 题；每卷两个知识点均有难度 2、3 各一题，学习题每知识点覆盖 1～5。难度 2 的学习题共 4 题，所以示例最多支持 4 道学习题的演练。正式研究须扩充题池并事先确定题数。

题目均为 **AI 编写、人工审核未完成的草案**。难度仅为候选标注，A/B 等价性尚未经人验证；data_kind=demo，不能启动 real_experiment。程序测试没有代替人审。

JSON 格式为 `schema_version=reviewed_question_bank_v1`，顶层包含 bank_id、version、data_kind（demo / real_candidate）、topics（ID→教学范围）及 items。每题包含：

- item_id、pool（A/B/learning）、topic_id、difficulty（整数 1～5）、family_id；
- stem、options（A/B/C/D 四个不同选项）、answer、explanation；
- provenance.kind（ai_generated / human_authored / reference_adapted）及 reference；
- review.status（draft / pending_review / approved / rejected）；批准后另含审核编号、带时区时间、五项检查、题目指纹和前一审核指纹。

机器检查实际字段；复用 S3 检查 A/B 知识点×难度计数一致、学习与测试覆盖相同知识点、学习题覆盖 1～5。NFKC/空白/大小写规范化后的重复题干、忽略选项标签与顺序后的重复内容、重复 ID 和规范化后重复家族均会被拒绝，包括同题池内复用。换数字/情境/措辞但解题路径相同的题，由人标为同 family_id；软件不能自动识别所有语义近似题。

人工逐题核验 content（事实、唯一答案、解析）、topic、difficulty、form_equivalence（全卷平行性）、family_disjoint（记忆污染）。修改已批准题的题干、选项、答案、难度、知识点、家族或来源会使批准失效。自动生成题和人写题适用同一准入门槛。

先复制到私有研究目录，确定实际内容和来源、设置 real_candidate，再审核。不要只改 demo 标签就宣称合格。全部 CLI 输出拒绝覆盖，保留审核版本。

```powershell
.\.venv\Scripts\python.exe -m scripts.experiment_bank prepare --bank .evaluation-private/my-study/bank-draft.json --output .evaluation-private/my-study/bank-prepared.json
.\.venv\Scripts\python.exe -m scripts.experiment_bank packet --bank .evaluation-private/my-study/bank-prepared.json --output .evaluation-private/my-study/review.md

# 人类核验后逐题批准，不提供批量自动批准；下一题使用上一步输出
.\.venv\Scripts\python.exe -m scripts.experiment_bank review --bank .evaluation-private/my-study/bank-prepared.json --item A-lists-length_after_pop --reviewer REVIEWER-01 --decision approve --checked content --checked topic --checked difficulty --checked form_equivalence --checked family_disjoint --note "人工核验说明" --output .evaluation-private/my-study/bank-reviewed-001.json
.\.venv\Scripts\python.exe -m scripts.experiment_bank validate --bank .evaluation-private/my-study/bank-approved.json --require-approved
```

题目 ID 应使用实际题库内的值，命令采用草案第一题作示例。prepare 只计算 content_hash，不批准题目。审题册包含答案，只给主持人。驳回题目使用 --decision reject；移除/调整题目后仍须满足蓝图。修改已批准题时先将该题 review.status 改回 pending_review，再 prepare、重新审查，保留旧版本。软件不能证明审核者是真人或确实完成检查；题目难度与等价性还需试测。

## 主持式终端流程

无需启动网页。主持人在受控本机运行，实际展示题干与选项，输入 A～D 后自动判分。前后测只确认保存，学习阶段显示正误及解析；前后测不进入学习策略。输入 q 暂停，相同研究编号再次进入可恢复。疲劳/退出保留缺失，不造剩余答案。

### 演练（demo）

```powershell
# 两个输出目录均需尚不存在
.\.venv\Scripts\python.exe -m scripts.create_review_bank --output-dir .evaluation-private/my-demo-bank
.\.venv\Scripts\python.exe -m scripts.research_experiment init --bank .evaluation-private/my-demo-bank/bank.json --participants .evaluation-private/my-demo-bank/participants-demo.json --source demo_experiment --study .evaluation-private/my-demo-study --learning-steps 4
.\.venv\Scripts\python.exe -m scripts.research_experiment conduct --study .evaluation-private/my-demo-study --participant DEMO-01
.\.venv\Scripts\python.exe -m scripts.research_experiment progress --study .evaluation-private/my-demo-study
```

每个完整演示含 4 道前测、4 道学习、4 道后测；进度表展示研究编号、分组、卷序、分阶段完成数、总进度和完成状态。

### 正式研究

1. 取得知情同意，仅用研究编号；身份对应表单独保管，编号不得含姓名/邮箱/学号。事先确定主要指标、时限、资料查阅规则、设备、题数、退出/停止条件与种子。
2. 人工审核完整实际题库，扩充到足够固定难度题数。准备研究编号 JSON 数组，冻结题库/计划，勿把 DEMO 编号当真人。
3. 复用 S3 固定种子分块随机分配：fixed/adaptive × A→B/B→A，完整四人块同时平衡模式及卷序，尾块不保证完全平衡。
4. 统一主持规范，按前测→学习→后测推进，结束后再反馈/访谈。测试题不复用，学习与测试家族不重叠。不要看结果后改题、种子、评分或停止条件。

```powershell
# 12 道学习题要求实际题库已扩充；题池不足会拒绝初始化
.\.venv\Scripts\python.exe -m scripts.research_experiment init --bank .evaluation-private/my-study/bank-approved.json --participants .evaluation-private/my-study/research-codes.json --source real_experiment --study .evaluation-private/my-study/run-01 --learning-steps 12 --fixed-difficulty 2 --seed 20261023
.\.venv\Scripts\python.exe -m scripts.research_experiment conduct --study .evaluation-private/my-study/run-01 --participant R001
.\.venv\Scripts\python.exe -m scripts.research_experiment progress --study .evaluation-private/my-study/run-01
```

两组共用原 S3 知识点选择器，只有难度政策不同：固定组请求 2，自适应组复用 rules_v2，仅依据已发生的学习答案。请求难度耗尽时，自适应选最近可用级别、同距取低，并保留请求/实际差异；固定组不换级。题池耗尽明确报告 bank_exhausted，不生成新题或重复题。

支持分步主持：next --study ... --participant ... --output decision.json 展示题目；answer --study ... --decision decision.json --answer A --duration-seconds 25 记录实际选项。decision 不含答案/解析。重复/旧决策、错阶段、非法用时和无时区时间被拒绝。conduct 使用单调时钟记录本次显示至提交用时，暂停题不补造时长。

## 存储、导出与 S3 分析

plan.json 冻结分组、算法和**私有题库答案**；observations.json 是唯一权威日志，存实际选项及 S3 记录行。提交使用独占锁、新鲜读取和前缀验证，自动判分后原子替换单个文件，CSV 是派生快照。若异常留下 .lock/.tmp，停止其他写进程、备份检查，确认无在途提交后再人工恢复，禁止盲删锁或猜测答案。

```powershell
.\.venv\Scripts\python.exe -m scripts.research_experiment export --study .evaluation-private/my-study/run-01 --output-dir .evaluation-private/my-study/export-01
.\.venv\Scripts\python.exe -m scripts.learning_experiment analyze --plan .evaluation-private/my-study/export-01/private-s3/plan.json --records .evaluation-private/my-study/export-01/private-s3/records.csv --output-dir .evaluation-private/my-study/s3-analysis-01
```

- private-s3/ 含冻结计划、原研究编号、标准 S3 CSV 和分析，**只给主持人保留，不能整体公开**。
- shareable/ 含 JSON/Markdown 分析、参与者 CSV、事件 CSV 和来源/指纹 manifest。每次导出用随机 HMAC 假名，绝对时间换成相对秒；不含原编号、题干、实际选项、身份表或生产用户信息。这是脱敏/假名化，不是不可重识别的匿名化。

分析复用 S3：完整参与者的前后测及增量，披露未开始/未完成、卷序和题池偏离。每组完整人数不足默认 5 人时，组间增量差/区间为 null、not_evaluable。达到门槛也只是探索性描述及参与者级 bootstrap，不能证明因果或学习改善。行数不是参与者数。

原 S3 图表脚本可用 --experiment-report shareable/experiment.json 附加实验样本量/增量图，同时仍需 --report-dir 指向原离线回放。两部分须分别说明数据来源，不能把历史观察队列与实验队列合并。无需重复开发回放或图表系统。

## 验证与数据标签

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.verify_experiment_workflow --output-dir .evaluation-private/s4-verification-new
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --experimental-vm-modules tests/frontend_practice.mjs
node --experimental-vm-modules tests/frontend_admin.mjs
node --experimental-vm-modules tests/frontend_coach.mjs
node --experimental-vm-modules tests/frontend_recommendation.mjs
node --experimental-vm-modules tests/frontend_study.mjs
```

本次独立文件端到端：4 个脚本研究编号、两种模式、28 道候选题、48 次脚本输入，所有阶段完成；前后测隐藏反馈、学习显示解析，S3 CSV 分析往返一致。输入循环 A/B/C/D，时钟为演示时间。**真实参与者 0 人**，没有真实实验成绩或学习效果结论。验证只操作独立目录，没有数据库访问/付费调用。摘要见 evaluation/reports/experiment-s4-verification.json，实际记录在被 Git 忽略的 .evaluation-private/s4-e2e/。

S3 synthetic/synthetic_experiment 是规则模拟；S4 demo_experiment 是实际题目上的操作/脚本演示；real_history 是既有观察记录；real_experiment 仅供已审题库上的真人研究，由主持人如实声明，软件不能证明真人身份。单元测试中的虚拟审核标记只存在临时测试数据，不是交付题库的人工批准。实际测试结果见 evaluation/reports/s4-tests.json。

最终回归实际结果：后端 239 项通过，失败/错误/跳过均为 0；前端 5 个自动化脚本全部退出码 0（admin、coach、practice、recommendation、study）。后端覆盖管理员、JWT、RAG、练习、XP、掌握度和 S3；新增关联与实验测试使用内存/临时数据库和独立文件。全程前后正式 learning.db 的 SHA256 一致。前端是 DOM/接口模拟测试，未进行真实浏览器视觉验收；Node 输出实验性 VM 模块提示，coach 测试另有 EventTarget 监听器数量警告，均保存在测试报告，未据此宣称生产内存泄漏或完全无风险。

## 文件及接口清单

| 类型 | 文件 |
| --- | --- |
| 关联与时间 | app/services/question_generator.py、topic_extractor.py、answer_submission.py；app/routers/question.py；app/agents/tools.py；app/models/question.py、topic.py；app/schemas/question.py |
| 练习入口 | frontend/practice.js、index.html、README.md |
| 研究核心 | 新增 evaluation/experiment_bank.py、experiment_session.py；调整 evaluation/learning_experiment.py 仅增加题库准入与 demo 来源，原策略不变 |
| CLI（新增） | scripts/audit_learning_links.py、create_review_bank.py、experiment_bank.py、research_experiment.py、verify_experiment_workflow.py |
| 测试 | 新增 tests/test_experiment_s4.py；调整 tests/test_question_generation.py、test_question_answer_flow.py、frontend_practice.mjs |
| 内容/文档/报告 | evaluation/examples/review-bank-s4/ 下 bank.json、review-packet.md、participants-demo.json；本文件；evaluation/README.md；S3_ADAPTIVE_EVALUATION.md 的后续提示；evaluation/reports/data-quality-s4.json、experiment-s4-verification.json、s4-tests.json |

仅调整 POST /questions/generate：要求有效 topic_id，题目响应增加可空 topic_id；历史题响应兼容。教练 create_practice 同样要求有效 ID。没有新增生产实验 API、数据库迁移或历史修复；模型列保持可空以兼容旧记录。

## 剩余限制

尚未招募真人、完成人工审题、实证标定难度或验证 A/B 等价性。每卷仅四题的草案不能作为可靠性证明。语义近似题依赖人工家族标注。研究终端面向受控设备上的主持人；私有文件没有新加密/认证，参与者不得接触答案文件、主持命令或管理员权限。指纹和锁防常见误操作，不能抵抗本地写权限者重新伪造整份数据。保存层校验不等于数据库非空约束，直接 ORM/SQL 维护仍须遵守规则，多进程首次提取知识点的强唯一约束留待后续迁移。历史缺失继续存在，不能补造关联提高论文样本量。
