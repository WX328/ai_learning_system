# 本地部署与恢复手册

适用：Windows Docker Desktop 的 Linux containers / Compose v2 或更高，以及 Python 3.13 本地运行。S5 实际环境与成功结果以 evaluation/reports/s5/ 为准。默认只监听本机，不包含公网 TLS 或云端上线。

## 配置与数据边界

仓库无旧 Docker/Nginx 配置，S5 新增一套 Compose：migrate 单次备份/迁移→app 健康→proxy 启动。maintenance 只用于人工维护。API 不发布主机端口；Nginx 默认 127.0.0.1:8080。

| 项目 | 位置/行为 |
| --- | --- |
| 运行时密钥 | .env.docker，Git忽略，构建白名单排除；不要放 Dockerfile/build args |
| SECRET_KEY | 至少32随机字节；变更会让所有旧JWT失效 |
| 数据 | learning-data 命名卷 /data/learning.db（含原文、向量、记录、XP和用户） |
| 原始上传文件 | 当前只在内存解析；数据库保存提取文本，/data/uploads 预留并纳入备份 |
| 备份 | learning-backups 卷 /backups；包含私人数据，需访问控制和异地加密副本 |
| 研究 | .evaluation-private 独立文件；不在生产镜像或数据卷内 |
| 配置 | APP_DATA_DIR=/data、SQLITE_WAL=true、APP_ENV=production；容器配置不沿用本机 .env |
| 健康 | /health/live 存活；/health/ready 验证数据库及迁移版本，不付费检测模型服务 |

不要设置 ALEMBIC_DATABASE_URL 指向其他库。不要把 .env、数据库或研究目录挂到代码目录。不要把生产配置与 compose.acceptance.yaml 混用。

## 第一次启动

在项目根目录执行。已有配置文件不要覆盖：

```powershell
Copy-Item .env.docker.example .env.docker
# 生成随机值后填入 SECRET_KEY，输出仅用于本机配置，不提交：
python -c "import secrets; print(secrets.token_urlsafe(48))"
# 编辑 .env.docker，设置 DEEPSEEK_API_KEY、DASHSCOPE_API_KEY、
# DASHSCOPE_EMBEDDING_BASE_URL（自己的工作区 HTTPS URL）。
docker compose up -d --build --wait
docker compose ps
docker compose exec app python -m scripts.init_admin
```

最后一条在交互终端执行，不加 -T，不传密码参数或管道。用户名、两次密码都不回显，使用新用户名，密码至少15字符；不会把已有普通用户提升为管理员。已有管理员不能再次初始化；遇到拒绝先检查是否已经创建，不要删除账号绕过。

访问 http://127.0.0.1:8080/app。普通用户页面注册；管理员登录后出现后台入口。初始新库种入3项基础成就，不创建任何用户。基础镜像/依赖首次拉取需要联网；运行中的 RAG/出题/教练使用配置的付费供应商。

端口可改：

```powershell
$env:APP_PORT='8081'
docker compose up -d --wait
```

后续命令保持相同的项目名、端口变量和配置文件。正式演示不要使用 --reload 或多个 worker。

## 停止、日志与升级

```powershell
docker compose logs --tail 100 app migrate proxy
docker compose logs -f --tail 100 app
docker compose stop
# down 也保留命名卷；不要追加 -v。
docker compose down
```

升级时先停止写入，保证代理重新解析后端容器地址：

```powershell
docker compose stop proxy app
docker compose build app migrate
docker compose run --rm --no-deps migrate
docker compose up -d --wait
docker compose exec app python -m alembic check
```

迁移前自动创建带UTC时间和随机后缀的独立备份；失败时 API 不启动，保留快照。不要通过降级 SQLite 迁移或覆盖旧库来碰运气；使用经校验的备份恢复到新卷。S5 无新增迁移，head仍是0005；已有用户和学习记录不回填。

## 手动备份和复制

工具使用 SQLite backup API，包含已提交的 WAL 数据；快照转换为独立非 WAL 文件，做 integrity_check、SHA256 文件清单并复制 uploads。不能只拷贝运行中的 learning.db。

```powershell
$snapshot='manual-'+(Get-Date -Format 'yyyyMMdd-HHmmss')
docker compose run --rm --no-deps maintenance python -m scripts.data_backup backup --database /data/learning.db --output-dir /backups/$snapshot
New-Item -ItemType Directory -Force .private-backups
docker compose cp app:/backups/$snapshot .private-backups/$snapshot
```

输出目录必须新建，不覆盖旧快照。manifest.json 记录版本、时间、哈希和迁移头。校验可以检测损坏，不证明备份来源真实、也不加密。异地副本需另行加密并定期演练恢复；两个卷仍在同一 Docker 宿主机，不能代替灾难恢复。若以后增加原件持久化写入，备份数据库和文件前还应暂停写入以保证两者一致。

本地 Python 备份：

```powershell
.\.venv\Scripts\python.exe -m scripts.data_backup backup --database learning.db --output-dir .private-backups/local-before-update
```

本机维护也可设置 APP_DATA_DIR 和 APP_BACKUP_DIR，再运行 scripts.container_start，确保目录已准备且有权限。已有库自动备份，不修改历史关联。

## 恢复到全新卷

恢复拒绝非空目录、路径穿越和哈希不符；不覆盖正在使用的数据库。下面创建独立恢复卷，原 learning-data 完整保留。BACKUP_NAME 换成 /backups 中实际快照目录名。

```powershell
docker compose stop proxy app
$env:RESTORE_VOLUME_NAME='zhixing-restored-20261026'
docker compose -f compose.yaml -f deploy/compose.restore.yaml run --rm --no-deps maintenance python -m scripts.data_backup restore --backup /backups/BACKUP_NAME --target-data-dir /data
docker compose -f compose.yaml -f deploy/compose.restore.yaml up -d --wait
docker compose -f compose.yaml -f deploy/compose.restore.yaml exec app python -m alembic check
```

同名恢复卷已有内容时换新卷名，工具不会帮忙删除。恢复后所有启动、备份、日志及停止命令都保留同样的 -f 配置和 RESTORE_VOLUME_NAME。去掉恢复配置会重新挂原 learning-data，而不是恢复后的数据。验证账号、记录数量、推荐、审计和健康，再决定使用哪个卷，不能运行 down -v。

已有本机数据迁入**尚未初始化的 Docker 卷**：先用本地工具生成完整快照，将 .private-backups 只读挂为 /import，启动前执行：

```powershell
docker compose run --rm --no-deps -v "${PWD}/.private-backups:/import:ro" maintenance python -m scripts.data_backup restore --backup /import/local-before-update --target-data-dir /data
docker compose up -d --wait
```

已有数据卷请走新卷恢复，不向非空 /data 复制文件；本机原数据库保持不动。备份保留密码哈希等私人数据，不上传作品集。

## 不付费的 Docker 验收

以下只运行在专门的 zhixing-s5-20261026 项目，使用新卷、随机合成账号和无外网模型替身；禁止指向正式学习库。应用仍执行真实HTTP、JWT、数据库和原有业务逻辑。替身服务不发布端口。

```powershell
.\.venv\Scripts\python.exe -m tests.s5_prepare
$env:APP_ENV_FILE='.s5-local/acceptance.env'
$env:APP_PORT='18080'
docker compose -p zhixing-s5-20261026 -f compose.yaml -f deploy/compose.acceptance.yaml up -d --build --wait
.\.venv\Scripts\python.exe -m tests.s5_bootstrap_fixture
.\.venv\Scripts\python.exe -m scripts.s5_acceptance --base-url http://127.0.0.1:18080 --credentials-file .s5-local/acceptance-credentials.json --model-source mocked_provider_http --report evaluation/reports/s5/docker-api.json
```

prepare 只在文件不存在时创建；重复使用时复用私有文件和既有管理员，不重复初始化。验收脚本每轮创建新合成用户，不清除旧数据；测试会启停测试账号。脚本管理员注入仅是固定测试项目的 fixture，强制 APP_ENV=test，生产管理员只能用交互 CLI。

浏览器工具可使用已有 Playwright；缺少时仅安装到被忽略的测试目录：

```powershell
npm install --prefix .s5-local playwright
$env:PLAYWRIGHT_MODULE=(Resolve-Path .s5-local/node_modules/playwright).Path
# 使用本机 Edge，不下载浏览器。EDGE_PATH 可覆盖安装路径。
node tests/s5_browser.mjs
.\.venv\Scripts\python.exe -m tests.s5_docker_verify
```

浏览器脚本驱动真实页面，无请求拦截替身，服务端模型才是替身。截图/报告在 evaluation/reports/s5/browser。Docker验收会暂停同项目的 app/proxy，备份、重启并创建全新恢复卷再启动；不要并行运行浏览器或操作该测试项目。测试中的 --wait 只是健康/启动检查，不代表供应商可用或安全认证。

验收后停止固定项目，保留卷：

```powershell
docker compose -p zhixing-s5-20261026 -f compose.yaml -f deploy/compose.acceptance.yaml stop
```

Docker恢复验收后的实际恢复卷名保存在 docker-deployment.json；再次使用该恢复实例要同时传 compose.restore.yaml 及相同卷名。测试结束后清除当前Shell的 APP_ENV_FILE/APP_PORT 再启动正常实例，避免误用测试变量。

## 回归与真实在线检查

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.run_s5_tests
.\.venv\Scripts\ruff.exe check --no-cache app tests scripts migrations rebuild_embeddings.py
# 有意启用少量真实模型调用，会产生费用，只使用新临时库：
.\.venv\Scripts\python.exe -X utf8 -m scripts.s5_online_check --run-live
```

在线检查读取本机 .env 中的运行时密钥，不输出密钥或Token，强制HTTPS供应商地址；新临时库、随机账号、服务退出后清理，正式 learning.db 不参与。报告分别标记 mocked_provider_http / live_provider；在线回答正确性未经人工全量审核，单次成功不是稳定性或学习效果证明。

## 资源、失败与公网边界

应用正文12MiB；每次最多5文件，每文件5MiB，提取文本20万字符、PDF100页、DOCX主XML解压5MiB；索引最多128分块。普通模型接口每用户每分钟20请求、进程内并发2；教练另有并发和轮数限制。读取推荐不占模型请求配额。Nginx API每来源10请求/秒、突发60，静态资源分开；不替代账号鉴权和模型费用控制。

SDK自动付费重试为0。默认单次超时：教练20秒、RAG/出题/提取60秒、反馈15秒、向量30秒；模型输出有token上限。分块分类最多8次、45秒预算；长资料可能关联不完整。批量3题和索引分批的总耗时仍可能超过代理180秒，前端会显示失败，不能盲目反复点付费操作。首次作答与复习不依赖额外AI反馈，提交结果仍可保存。

本机故障检查：配置缺失/短密钥/非HTTPS地址→修配置；迁移失败→看 migrate 日志和备份；502/超时→确认供应商及工作区；429→按提示稍后手动重试；磁盘满→停止写入、先备份、清理已确认可丢弃的构建缓存，绝不删数据卷。健康检查不证明外部API余额、语料质量或磁盘容量充足。

公网前必须补TLS与可信代理边界、备份加密及访问控制、供应商预算告警、依赖和镜像漏洞扫描、容量/磁盘监控和限流策略。当前 JWT 在 localStorage，XSS可窃取；不要放宽 CSP 或把不可信HTML直接插入页面。普通请求/登录限流是单进程，SQLite是单写者；多worker或多实例需重新评估共享限流与事务，不能直接横向扩容。
