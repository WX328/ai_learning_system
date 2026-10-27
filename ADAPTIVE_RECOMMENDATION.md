# AI 自适应学习推荐卡片

S2 已将掌握度升级为难度加权、样本平滑与有限复习贡献的统一规则模型，详见 [S2 算法与验证](S2_TOPIC_MASTERY.md)。本页后面的 137 项测试结果为 S1 历史记录，S2 最新结果见新文档。

## 现有实现与本次范围

原项目已有 JWT/资料归属检查、知识点答题记录、掌握度更新、按正确率调整难度、
`GET /adaptive/next-question`、未完成自适应题目复用及前端 `study-updated` 事件。
本次复用这些流程，补充只读推荐与动态卡片。没有引入框架或数据库迁移。

原有问题是：没有记录返回 0%，新用户被误降级；只有存在 `TopicMastery` 的薄弱点才能推荐；
自适应出题每次从难度 2 起算；推荐前必须出题。现在推荐可以独立读取，首次练习也可开始。

## 接口与字段

新增 `GET /adaptive/recommendation?material_id=123`，必须携带 `Authorization: Bearer <JWT>`。
无效或过期 JWT 返回 401；其他用户的资料、资料不存在均返回 404。

```json
{
  "material_id": 123,
  "topic": {"id": 8, "name": "依赖注入"},
  "mastery_score": 60,
  "recent_correct_rate": 0.8,
  "recent_attempt_count": 5,
  "attempt_count": 10,
  "current_difficulty": 2,
  "recommended_difficulty": 3,
  "has_history": true,
  "pending_question_id": null,
  "reason": "优先巩固当前掌握度较低的知识点。该知识点最近 5 次首次作答正确率 80%，建议提高一档（范围 1～5）。"
}
```

无历史时 `mastery_score`、`recent_correct_rate` 为 `null`，次数为 0，默认难度 2；
没有知识点时 `topic` 为 `null` 并给出整理知识点的提示，前端禁用开始按钮。
此接口仅查询数据库，不生成题目、写入掌握度、奖励 XP、调用向量/重排/大模型服务。

原有 `GET /adaptive/next-question?material_id=123` 保留 URL 与题目返回结构，
调整为采用相同推荐计算，支持新用户与全部已掌握后的巩固练习。题目不返回答案或解析。
已有未完成题目时两接口推荐同一知识点与难度；连续重复请求复用原题。
只有点击“开始练习”且没有未完成题目时才进入原有 AI/RAG 出题流程，使用原有模型配置和费用。

## 数据流与算法

1. 进入练习页并选择资料，卡片读取推荐接口；页面刷新和重复点击共享正在进行的读取。
2. 后端按 JWT 用户、当前资料、真实知识点 ID 读取答题和复习记录。
3. S2 掌握度使用统一规则模型：每题复习贡献最多 30%，结合难度权重与样本平滑，历史证据占 70%、最近 5 道证据占 30%，输出 0～100 规则分。
   读取时直接计算，兼容旧记录没有 `TopicMastery` 的情况，不创建或修复数据库行。
4. 优先推荐掌握度低于 80 分的已练知识点，分数越低越优先；之后推荐未练知识点；
   全部达到 80 分后选择掌握度较低、练习较少的点巩固。同分同次数按知识点 ID 排序。
5. 最近正确率仅统计选中知识点最近最多 5 次**首次作答**，不足 5 次按实际次数计算。
   按答题时间倒序、ID 倒序排列，不混入其他用户或其他知识点的数据。
6. 以该知识点最近一次已答题的难度为基准：正确率 ≥80% 且最近窗口至少 3 道不同题目时加 1；<50% 减 1；
   50%～不足80% 不变；最终限制在 1～5。无记录使用难度 2，不假设 0% 正确率。
7. 未完成自适应题目优先继续，卡片解释为何保留原难度。出题复用原有生成器与保存逻辑，
   关闭第二次难度调整，确保卡片建议与题目难度一致。
8. 答题、错题重答、错题本复习保存后，通过原有 `study-updated` 事件刷新；
   若此时已有读取，则读取完成后再补一次更新。页面隐藏时标记过期，下次打开再读取。
   资料切换、退出/切换账号时丢弃旧响应。出题/答题锁定仍使用原有练习系统。

掌握度和最近正确率有不同用途：复习可以提升掌握度，但不会反复增加“最近 5 次首次作答”的样本数。
卡片明确展示样本数量，并将未评估与真实 0% 区分。

## 启动与手动验证

在 PowerShell 中执行（使用现有 `.env`，不要将密钥提交到版本库）：

```powershell
Set-Location <PROJECT_ROOT>
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

访问 `http://127.0.0.1:8000/app`，登录，选择已整理知识点、已完成索引的资料，进入练习中心。
新用户应看到“尚未评估 / 暂无答题记录 / 2 星”。点击开始、完成答题，卡片自动更新。
同一知识点最近 5 次答对 4～5 次应提高一档，答对 0～2 次降低一档，答对 3 次保持。
难度 1、5 不越界。连续刷新卡片不生成新题；重复开始复用未完成题。
可在开发者工具暂时阻断推荐接口，验证卡片内错误提示和恢复后的刷新。
手机宽度下推荐卡片先于普通练习设置展示。

资料尚未整理知识点时先回资料库准备资料；缺少相关正文/索引时出题仍可能按原逻辑报错。
推荐读取本身无需执行模型调用，但应用启动仍遵循原有密钥与数据库版本检查。

## 自动化验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m ruff check app/services/adaptive.py app/services/topic_mastery.py app/services/question_generator.py app/routers/adaptive.py tests/test_adaptive_recommendation.py
Get-ChildItem tests/frontend*.mjs | ForEach-Object { node --experimental-vm-modules $_.FullName; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
```

新增 `tests/test_adaptive_recommendation.py` 与 `tests/frontend_recommendation.mjs`。
覆盖新用户、零正确率、阈值与边界、最近 5 次、知识点/用户隔离、JWT 过期、无知识点、
重复只读请求无写入/无 AI、出题一致性、未完成题复用、答题/复习与 XP、错误恢复、
重复点击、请求中更新、账号和资料切换竞态。

真实浏览器 QA 使用 `.taste-skill/preview_adaptive.py` 的临时数据库、真实 JWT/接口及本地模型替身；
`.taste-skill/check-adaptive.mjs` 驱动本机浏览器。截图与检查报告在 `.taste-skill/adaptive/`。
不会读取或修改正式学习数据库，也没有调用付费模型。

2026-10-22 实际执行结果：完整后端 **137/137 通过**（其中新增推荐测试 14 项，
完整运行耗时 27.087 秒）；前端 `frontend_coach.mjs`、`frontend_practice.mjs`、
`frontend_recommendation.mjs`、`frontend_study.mjs` 四个脚本全部通过；本次 Python 文件 Ruff 检查通过。
真实浏览器登录、推荐、重复点击、出题、答题/XP、自动刷新、错误与重试检查通过；
1440/768/390px 无横向溢出，开始按钮触摸高度至少 44px。
最终布局检查为 0 FAIL / 0 WARN（按用户要求保留难度星级，检查时允许星字符）。
后端完整输出见 `.taste-skill/adaptive/backend-tests.txt`，浏览器报告见 `browser-report.json`，
布局报告见 `inspect/report.json`。

## 修改文件

- `app/services/adaptive.py`：推荐选点、默认值、历史难度基准与生成一致性。
- `app/services/topic_mastery.py`：新增只读知识点表现汇总。
- `app/services/question_generator.py`：增加内部开关，避免重复调整已确定的推荐难度。
- `app/routers/adaptive.py`：推荐接口、共享鉴权/归属检查、未完成题返回一致性。
- `frontend/recommendation.js`：新增卡片数据、状态、缓存失效与请求竞态处理。
- `frontend/practice.js`：卡片初始化、复用原练习按钮与答题事件。
- `frontend/index.html`、`frontend/workspace.css`：卡片结构、星级、进度条与响应式布局。
- `tests/test_adaptive_recommendation.py`、`tests/frontend_recommendation.mjs`：新增自动化测试。
- 本说明及 `.taste-skill/preview_adaptive.py`、`.taste-skill/check-adaptive.mjs`、
  `.taste-skill/adaptive/`：交付说明与本机隔离 QA 记录。已有工作区改动保留。

## 限制

- 未执行付费模型的真实出题质量评估；模型调用/检索失败沿用原有错误处理。
- 近期难度按首次作答调整，复习影响掌握度及选点，不增加近期正确率样本。
- 掌握度查询读取当前资料的全部历史答题/复习记录，大量历史数据后可进一步改为 SQL 聚合。
- 保留现有出题接口的未完成题复用机制，未增加多进程/多服务实例的并发出题分布式锁。
