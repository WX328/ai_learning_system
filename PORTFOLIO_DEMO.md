# 作品集演示与独立复现

使用单独目录、新数据库与合成账号。不要在包含正式学习资料的服务上运行验收脚本。端口8080为正常本地部署示例，18086为本轮隔离验收；均绑定127.0.0.1。本文件不会触发发布或调用付费模型。

## 无模型费用演示（Docker）

需要 Docker Engine + Compose v2兼容命令、Python 3.13。后端依赖见锁文件；前端无需构建。先克隆到自己的目录，或使用本机白名单导出的候选快照进入根目录；以下不依赖作者的磁盘路径。若创建虚拟环境失败，先安装对应 Python。

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
# 只在新的演示目录运行；已有私有文件会拒绝覆盖。
.\.venv\Scripts\python.exe -m tests.s5_prepare
$env:APP_ENV_FILE='.s5-local/acceptance.env'
$env:APP_PORT='18086'
docker compose -p zhixing-demo-local -f compose.yaml -f deploy/compose.acceptance.yaml up -d --build --wait
.\.venv\Scripts\python.exe -m tests.s5_bootstrap_fixture --project zhixing-demo-local
.\.venv\Scripts\python.exe -m scripts.s5_acceptance --base-url http://127.0.0.1:18086 --credentials-file .s5-local/acceptance-credentials.json --model-source mocked_provider_http --report .s5-local/api-report.json
```

打开 http://127.0.0.1:18086/app。`.s5-local/acceptance-credentials.json` 是本机随机生成的**一次性工程账号**；在本地编辑器查看 admin 的用户名/密码登录，演示或录屏时不要展示此文件。也可在界面注册一个新普通账号。验收脚本为 learner/other 追加随机后缀，文件内 learner 名不是该次 API 运行最终注册名。管理员后面可以停用自己在界面注册的合成账号。

替身服务仅存在于 acceptance overlay，返回确定性的依赖注入例题/证据，适合演示交互、事务和权限；它**不会根据任意资料生成真实内容**，不能拿它比较模型质量。不要在真数据部署中使用该 overlay。

合成展示资料：[demo-notes.txt](docs/portfolio/demo-notes.txt)。本轮截图均来自临时数据库/账号，非真实参与者，来源见[截图说明](docs/portfolio/README.md)。

```powershell
# 状态、日志与停止（保留卷）
docker compose -p zhixing-demo-local -f compose.yaml -f deploy/compose.acceptance.yaml ps
docker compose -p zhixing-demo-local -f compose.yaml -f deploy/compose.acceptance.yaml logs --tail 100 app proxy
docker compose -p zhixing-demo-local -f compose.yaml -f deploy/compose.acceptance.yaml stop
```

不要对真实项目使用 down -v。恢复等操作见[部署手册](DEPLOYMENT.md)。本轮 S6 为避免覆盖已有镜像标签，额外使用仅在私有验收目录的镜像名覆盖文件；服务定义和业务代码仍为现有 S5 配置。

## 正常模型版本

按 [README](README.md)和[部署手册](DEPLOYMENT.md)配置自己的随机 SECRET_KEY、DeepSeek 和百炼密钥、正确的工作区地址，使用标准 compose.yaml，不加载 acceptance overlay。真实问答/出题会产生供应商用量。不要把 `.env`、`.env.docker`、数据库、账号密码或演示时的开发者工具请求头录入公开视频。

公开仓库不包含作者的学习资料原文、向量库或既有账号。RAG 旧100题标签绑定当时的片段 ID，因此空库不能原样复跑旧检索成绩；可以查看冻结报告，或导入自己可分发的语料后重新标注新评测集。程序单元测试和合成自适应回放可以独立运行。

## 8～10 分钟演示脚本

| 时间 | 操作 | 要说明和核对的事实 |
| --- | --- | --- |
| 0:00～1:00 | 用1分钟讲稿，展示架构图 | 原生前端、FastAPI、SQLite；单教练 Agent；演示是否为替身必须先说清。 |
| 1:00～2:00 | 注册普通演示账号，上传 demo-notes.txt | 不展示密钥和终端凭据；等待索引及知识点整理完成。 |
| 2:00～3:00 | 问“Depends 如何注入依赖”，查看来源 | 资料与用户范围先验证；替身内容不代表真实模型质量。 |
| 3:00～4:30 | 练习卡片→开始练习→刻意选择错误项 | 无历史显示未知；单题只做初步评估；答题后推荐刷新，查看掌握度和难度原因。 |
| 4:30～5:30 | 查看地图，再到错题复习答对 | 同一掌握度服务；复习改善有限证据，不增加不同题样本，不刷XP。等待地图节点出现后讲解。 |
| 5:30～6:30 | 教练创建计划、要求解释和练习，刷新恢复 | 五个工具、服务端范围、回执/版本；判分共用事务，别把工具列表当成无限自主执行。 |
| 6:30～7:30 | 用另一个浏览器上下文登录管理员，搜索普通账号并停用 | 第二上下文中普通账号旧JWT请求被拒；重新启用仍需登录；展示审计，不展示私人正文。 |
| 7:30～9:00 | 展示测试分层和 S3 比较图 | 最近五题优于S2的合成结果公开；真实样本不足、S4零真人，无学习效果结论。 |
| 9:00～10:00 | 查看健康、持久化和备份/恢复报告 | 恢复演练使用新卷；本地部署验收不等于公网安全认证。 |

## 回归与评估

```powershell
# 后端、DOM、依赖：新报告目录，避免覆盖冻结的 S5 证据
.\.venv\Scripts\python.exe -X utf8 -m scripts.run_s5_tests --output-dir .s6-local/my-regression
.\.venv\Scripts\ruff.exe check --no-cache app tests scripts migrations rebuild_embeddings.py
# 不读取正式数据库、不调用模型
.\.venv\Scripts\python.exe -m scripts.evaluate_adaptive --dataset evaluation/adaptive_s3_synthetic.json --output-dir .s6-local/my-replay
# 绘图是可选评估依赖，生产镜像无需安装
.\.venv\Scripts\python.exe -m pip install -r evaluation/requirements.lock
.\.venv\Scripts\python.exe -m scripts.plot_adaptive_evaluation --report-dir .s6-local/my-replay --output-dir .s6-local/my-replay/figures
```

浏览器测试复用 `tests/s5_browser.mjs`，需要 Node.js、Microsoft Edge 与 Playwright（本轮使用现有工具运行库，项目不新增前端框架）。设置 `S5_BASE_URL`、`S5_CREDENTIALS_FILE`、`S5_BROWSER_OUTPUT`；可用 `PLAYWRIGHT_MODULE` 指向已有安装。默认输出仍为S5，S6必须指定新目录。该脚本新建合成账号并进行实际停用操作，只对隔离部署运行。

## 发布前本地快照

```powershell
.\.venv\Scripts\python.exe -m scripts.audit_portfolio --output .s6-local/release-audit.json
.\.venv\Scripts\python.exe -m scripts.prepare_portfolio --output-dir .s6-local/release-candidate-new
```

第二条命令复制白名单候选文件并生成 RELEASE_MANIFEST.json，不带 `.git` 历史、正式库、私有研究文件或运行时凭据，不执行 add、commit、push。输出目录必须不存在。该快照只是人工审核候选，不能替代原仓库历史审查，新增文件后应重新扫描/生成。发布仓库、许可证、素材权利及最后公开操作由作者确认。
