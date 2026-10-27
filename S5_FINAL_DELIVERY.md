# S5 最终工程验收、部署与作品集交付

验收日期：2026-10-26。项目：AI 学习系统 V2 / 知行。结论：已完成本地可复现部署、隔离业务验收、备份恢复和作品集文档；当前具备本机演示条件，未实施公网发布。生产规则保持 rules_v2，S5 没有新增普通业务模块或数据库迁移。

## 先检查得到的状态与实施范围

已检查 README、S2/S3/S4交付、用户/JWT/RBAC、上传/分块/知识点、RAG、出题/答题/复习、统一学情、教练、前端ES Modules和现有测试。现有 S3 时间回放/实验分析和 S4 审题/主持式流程足够，继续复用。

起始仓库没有 Dockerfile、Compose、Nginx。API原本依赖项目根 learning.db、启动配置和迁移检查。上传原文件不落盘，解析文本存入数据库；不要把预留 uploads 目录描述成原件归档功能。

最小改动集中于部署生命周期、已有接口的输入/资源保护、同用户答题事务和验收工具。没有更换数据库/前端，没有引入 Agent 框架，也未调整 S2 参数、S3统计口径或 S4真实实验准入。

## 实际完成

| 范围 | 完成内容 |
| --- | --- |
| 学习闭环 | 保留并验收注册登录、上传、向量索引、知识点、带证据RAG、出题、答题反馈、掌握度、推荐、复习、XP/成就、教练与记录 |
| 管理 | 保留服务端JWT/RBAC、分页搜索、最小化详情、启停、最后管理员/自禁用保护与审计 |
| 本地容器 | 非root/只读应用、Nginx本机入口、独立数据/备份卷、一次性迁移、健康与启动依赖 |
| 配置 | 运行时密钥、32字节以上签名密钥、生产HTTPS供应商地址；镜像构建白名单排除真实数据/研究/密钥 |
| 数据 | APP_DATA_DIR、SQLite忙等待/外键、Docker WAL；迁移前一致快照；校验后恢复到全新空卷 |
| 资源 | 请求/文件/文本/PDF/DOCX/分块限制、普通模型接口速率/并发、输出token与分块分类预算 |
| 事务 | 首次答题条件更新串行化同用户XP/成就决策，重复请求不重复领奖，不丢并发XP |
| 交付 | README架构/流程/实验边界、DEPLOYMENT操作手册、分层JSON/日志/浏览器截图及本文件 |

没有修改正式历史答题、推断NULL知识点或回填数据库。无新增支付/消息/云服务。

## 实际执行的测试

下表只列最终已执行结果，分别标记模型来源。所有工程账号、上传资料、作答均为合成验收数据；**真实参与者0人**，不构成学习实验。

| 层次 | 实际结果 | 模型与数据来源 | 证据 |
| --- | --- | --- | --- |
| 后端全回归 | **253项通过，0失败/错误/跳过**；unittest报告68.670秒 | 各测试的替身，独立内存/临时库；含新增14项S5专项 | [日志](evaluation/reports/s5/backend.log)、[命令/进程墙时](evaluation/reports/s5/regression.json) |
| 前端DOM回归 | **5脚本全部退出码0** | DOM/接口替身 | 同目录frontend_admin/coach/practice/recommendation/study.log |
| pip check | 退出码0 | 本机依赖一致性，不是漏洞扫描 | [日志](evaluation/reports/s5/pip-check.log) |
| Ruff | 全范围检查通过 | app/tests/scripts/migrations/rebuild_embeddings.py，--no-cache | [收尾核对](evaluation/reports/s5/final-checks.json) |
| Docker全流程API | **78项检查通过** | 真实Nginx/HTTP/JWT/SQLite；本地模型HTTP替身 | [docker-api.json](evaluation/reports/s5/docker-api.json) |
| 在线模型API | **78项检查通过** | 真实本机HTTP/JWT/临时SQLite + 实际DeepSeek/百炼HTTPS供应商 | [online.json](evaluation/reports/s5/online.json) |
| 浏览器 | **8组交互通过，pageerror为空**；1440px及390px | 实际Edge/Playwright、实际DockerAPI；仅模型为替身 | [报告](evaluation/reports/s5/browser/report.json)；旧截图保留在原项目，公开展示采用[有来源说明的S6截图](docs/portfolio/README.md) |
| Docker部署/恢复 | **12项检查通过** | 实际容器、WAL数据、命名卷及新恢复卷；模型替身 | [docker-deployment.json](evaluation/reports/s5/docker-deployment.json) |
| 默认production配置 | **6项检查通过** | 独立Compose项目、运行时真实配置；不调用模型 | [production-boot.json](evaluation/reports/s5/production-boot.json) |

后端覆盖管理员、JWT、RAG、题目、XP、成就、教练、S2～S4及新增的并发答题、跨用户学习记录引用、流式正文超限、DOCX解压限制、模型预算/HTTPS、知识点分类截止、WAL备份、完整性/路径/覆盖/递归保护及重复迁移。

真实HTTP检查使用真实签发JWT，验证401/403、注册不能设置role、跨用户资料/题目/教练访问拒绝、禁用后旧JWT及登录失效、启用后旧JWT仍无效、重新登录与审计。跨用户答题沿用403，其余部分资源采用404；没有把两者都描述成同一种返回码。

在线通过包括真实向量化、提取、RAG、出题、反馈及教练，没有以替身冒充供应商。该轮答错后复习、推荐/地图一致、XP不重复等也有实际接口断言；不代表所有模型输出都正确，未测线上SLA或真实用户效果。此前一次在线检查遇到Windows进程清理失败，未形成完整报告，不计入通过；最终修正后重新运行成功。

浏览器实际点击注册/登录、上传并整理、RAG、推荐练习和答案、错题复习/地图/记录、教练创建/解释/结束、管理员搜索/详情/停用确认/审计及停用登录拒绝。验证普通用户无入口、390px无页面横向溢出。pageerror为空不能代替所有设备/无障碍或内存测试；未在浏览器里再重复付费在线模型流程。

早期验收发现的WAL备份辅助文件、代理静态资源误限流已修正；测试fixture缺失必填字段、选择器不唯一和返回码预期也已修正并复测。Node仍有VM Modules实验提示及既有coach监听器数量提示，未隐藏为“无警告”。

## 已验证部署环境与数据保护

- Windows宿主机，Docker Desktop Linux containers；Docker **29.8.0**，Compose **5.5.1**。
- 容器Linux x86_64、Python **3.13.17**；本机Python **3.13.2**。
- Edge **156.0.4314.42**，1440×1000及390×844；未验证其他浏览器/ARM。
- Python和Nginx基础镜像按本次拉取摘要固定，Python包锁定在 requirements.lock。应用实际镜像ID和恢复卷名写入部署报告；固定摘要不等于经过漏洞认证。
- 后端未发布主机端口；代理只绑定127.0.0.1。容器运行非root、只读根目录、丢弃capabilities；镜像无 .env、正式 learning.db 或研究目录。
- 自动迁移前先生成一致快照；恢复核对哈希和完整性，拒绝非空目录与穿越路径。实际验证新卷恢复后应用重新健康启动，迁移与ORM一致。
- 正式 learning.db 在测试前后 SHA256 均为：

```text
REDACTED_PRIVATE_DATABASE_SHA256
```

隔离测试项目使用 zhixing-s5-20261026 和 zhixing-s5-production-20261026，运行时测试凭据位于被忽略的 .s5-local；不写镜像和公开报告。正式库未运行S5迁移或业务写入。临时在线数据库不复用正式学习资料。验收结束停止专用容器，保留测试卷和备份，不执行 down -v，不停止用户原本8000端口的开发服务。

## 安全与稳定性结论

严重性针对已检查场景，不是渗透测试认证。范围内未发现未处理的P0问题，不表示证明不存在漏洞。

| 级别 | 发现及处理 | 验证/边界 |
| --- | --- | --- |
| P1 已修复 | 同账号并发首次答题可能重复记录/领奖，或不同题丢XP | 条件原子更新及同用户写入串行化；双线程同题/不同题断言 |
| P1 已修复 | 手动学习记录可引用他人资料/题目ID | 对支持的引用类型校验所有权，跨用户404、未知类型422 |
| P1 已修复 | 部署若复制整个目录会夹带密钥/正式数据库 | 构建白名单、运行时env文件、独立卷及实际镜像检查 |
| P1 已修复 | 直接文件备份无法保证WAL一致；恢复易覆盖数据 | SQLite backup、独立快照、清单/完整性、空卷恢复；递归目标拒绝 |
| P1 已修复 | 上传和模型资源缺少统一入口限制 | 正文/解析/分块限制、普通接口速率并发、输出和分类预算；容器资源限额 |
| P2 已修复 | 静态资源占用API配额导致首次正常页面429 | Nginx静态与API分开，浏览器完整复测 |
| P2 已修复 | 中文检索锁文件缺少jieba，默认容器不能可靠切到BM25 | 补版本锁，真实Linux容器分词检查 |
| P2 已修复 | 注册用户名并发冲突可能500 | 捕获唯一约束冲突并回滚；不更改注册权限策略 |
| P2 已修复 | 分块分类调用次数随大资料无限增长、打印模型全文 | 最多8次/45秒预算，去除正文输出；未关联保留空 |

### 尚未解决、尚未验证

1. **公网前置项**：未配置TLS/域名、共享限流、异地加密备份、供应商消费硬额度/告警、磁盘监控或依赖/镜像漏洞扫描。当前只允许本机演示；上线前必须补齐适用项。
2. **Token与请求生命周期**：JWT在localStorage，XSS可窃取；CSP与转义不是XSS无风险证明。停用阻止后续认证，已开始的外部模型调用不保证立即取消或免除费用；并发首答写入另校验活跃状态和版本。
3. **容量**：限流和教练并发是单进程内存预算，普通模型2并发与教练2并发分别计算。SQLite单写者，未做负载/长稳/断电/磁盘满注入或多实例测试。
4. **模型及费用**：SDK自动重试为0，但手动重试、批量出题、向量分批和教练工具会增加调用。部分批量请求总耗时可能超过代理180秒，不能据单次超时判断供应商没有执行。普通出题没有通用请求幂等键，前端防重复不能覆盖外部并发调用。尚无按金额计量的账户预算。
5. **数据质量**：历史41条首次答题和5条复习仍无法归因知识点，不回填；大资料分块分类预算可能只覆盖一部分。新题保存层强制有效关联，直接SQL维护仍可破坏约束；首次并发提取知识点的强唯一约束留待专门迁移。模型难度未经心理测量标定。
6. **备份边界**：哈希防损坏，不验证来源或加密。备份与数据库同宿主机，需异地副本。当前没有原件落盘；未来文件写入应暂停写入保证文件/数据库一致性。恢复不是原地覆盖。
7. **实验**：无真人前后测、无学习效果/显著性结论。S3真实历史样本不足，S4候选题仍待人工审核。工程验收账号不能当实验参与者。
8. **其他交付边界**：Shell中的Git检查曾返回“must be run in a work tree”；最终独立进程的diff --check可以执行，但退出码为2，仍有格式检查问题及换行提示，详情见final-checks.json。未将Git差异检查计为通过，未修改Git配置或创建提交；另以S5文件哈希清单核对交付。

## 架构、数据流与接口

总体架构、RAG流程、教练工具流程、权限及数据库ER图见 [README](README.md)。生产链路为：原生JS→本机Nginx→FastAPI鉴权/归属→服务→SQLite或模型。答题在一个事务内保存首次记录、XP/成就、掌握度快照和学习记录；复习独立幂等记账、XP为0；推荐/地图/教练读取统一rules_v2实时评估。

S5新增运维接口：

- GET /health/live：存活，不调用模型。
- GET /health/ready：数据库及Alembic版本就绪，失败503，不暴露异常细节。

原业务URL保留。部分写接口新增413/429和手动引用422；已有鉴权/归属检查继续执行。没有新增管理员提权API或生产研究API。S5无迁移；新库/已有库都通过Alembic到0005。

## 修改/新增文件

| 类别 | 文件 |
| --- | --- |
| 配置与部署 | Dockerfile、compose.yaml、.dockerignore、.env.docker.example；deploy/nginx.conf、Dockerfile.stub、compose.acceptance.yaml、compose.restore.yaml；.env.example、.gitignore、requirements.lock |
| 数据/入口/配置 | app/database.py、main.py、core/settings.py；新增core/resource_limits.py |
| 原接口保护 | app/routers/adaptive.py、learning_material.py、learning_record.py、question.py、rag.py、user.py；app/schemas/learning_material.py |
| 原服务加固 | app/services/answer_submission.py、answer_feedback.py、question_generator.py、rag.py、topic_chunk.py、topic_extractor.py |
| 部署维护脚本 | 新增scripts/container_start.py、data_backup.py、seed_achievements.py |
| 验收脚本 | 新增scripts/run_s5_tests.py、s5_acceptance.py、s5_online_check.py |
| 测试工具 | 新增tests/test_s5_delivery.py、s5_model_stub.py、s5_prepare.py、s5_bootstrap_fixture.py、s5_browser.mjs、s5_docker_verify.py、s5_production_boot.py |
| 测试清理 | tests/test_experiment_s4.py仅移除未使用的导入 |
| 文档 | 重写README.md；新增DEPLOYMENT.md、本文件 |
| 验收证据 | evaluation/reports/s5下JSON、测试日志、浏览器截图、source-manifest.json、final-checks.json |

前端业务源文件、User/JWT/RBAC模型与管理员接口、rules_v2和S3/S4核心未作本阶段改写。完整相对路径与SHA256见 [文件清单](evaluation/reports/s5/source-manifest.json)，不包含真实密钥、Token或私人数据。

## 启动和操作

完整命令以 [DEPLOYMENT.md](DEPLOYMENT.md) 为准：

1. 复制并填写 .env.docker，生成自己的随机签名密钥，配置HTTPS供应商地址；不要把 .s5-local 替身配置用于正式实例。
2. docker compose up -d --build --wait；交互执行 docker compose exec app python -m scripts.init_admin。
3. 打开 http://127.0.0.1:8080/app；普通账号从页面注册。
4. 维护时先备份，更新先停proxy/app、构建、迁移、再启动；恢复只到新空卷。
5. python -m scripts.run_s5_tests 生成实际回归报告；替身Docker、浏览器与在线模型分别按手册运行。在线检查需 --run-live，会产生供应商费用。

## 面试演示建议（8～10分钟）

| 时间 | 演示与说明 |
| --- | --- |
| 0～1分钟 | 介绍闭环和架构；显示容器健康，说明本机入口、独立卷与模型来源 |
| 1～3分钟 | 注册普通账号，导入可公开小资料；展示三阶段真实进度、知识点及有来源RAG |
| 3～5分钟 | 推荐卡片开始练习，答错一题；解释单题不等于0/100、地图一致、推荐依据 |
| 5～6分钟 | 复习答对，展示掌握度有限变化但不重复XP，打开学习记录 |
| 6～7分钟 | 教练创建目标、资料解释与一道练习，刷新恢复后结束，说明工具及循环边界 |
| 7～8分钟 | 管理员最小化详情/搜索，停用测试账号，展示旧JWT失效及审计；不展示真实用户信息 |
| 8～10分钟 | S3三规则含不利结果、真实样本不足、S4未审题库；展示备份恢复及分层验收，不宣称学习效果已提升 |

演示前确认网络/模型余额；无网络时使用明确标注的隔离替身环境，并向观看者说明。不要把演示成绩写入真人研究报告，也不要在录屏中展示.env或测试密码文件。
