# 管理员与用户管理（第一阶段）

## 现有实现与改动范围

原系统使用 Argon2 密码哈希、JWT 和 `get_current_user`，每次认证查询数据库；资料、题目、学习记录和教练会话已有用户关联。前端通过 `/auth/me` 恢复身份，使用原生模块、共享事件和 `core.js` 切换页面。已有 Alembic 版本为 `0004`。

本次沿用这些入口，增加账户字段、管理员依赖、单个管理员路由、一个前端模块和样式文件。没有调整学习、RAG、教练、XP、成就或自适应算法。

## 数据库迁移与备份

`0005_admin_rbac.py` 在 `users` 上增加：

- `role`：只允许 `user` / `admin`，旧用户默认 `user`。
- `is_active`：旧用户默认启用。
- `created_at`：新注册记录真实 UTC 时间；历史用户时间未知，保留 NULL，前端显示“历史时间未知”。
- `auth_version`：默认 0，用于撤销已经签发的 JWT。

新增 `admin_audit_logs`，记录操作者、目标、操作、结果、前后状态及 UTC 时间。没有更改学习表的内容或关联。

本次已先使用 SQLite 在线备份生成：

`.backups/learning-before-admin-20261022T065323022730Z.db`

然后将现有数据库升级到 `0005`。迁移前后对 14 张原有表的全部原始字段与记录计算摘要并逐表核对，全部一致；数据库完整性与外键检查通过。备份含原有私人数据，仅保存在本机，已通过 `.gitignore` 排除。

在其他部署上升级时，先停止应用的写入，再在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.migrate_admin
```

该工具先备份、检查备份，再运行 Alembic；最后校验原始数据和数据库完整性。重复运行也会生成新的备份，Alembic 已到最新版本时不会重复添加字段。测试通过 `config.attributes["database_url"]` 指定独立临时数据库；应用仍沿用原来的 `learning.db`。

需要恢复时，先停止所有使用数据库的进程，保留当前库供排查，再用备份恢复并运行与备份数据库版本匹配的代码。直接降级会删除新管理员字段与审计表，不作为日常回滚方式。

## 初始化管理员与启动

本次没有在正式数据库中创建管理员，也没有预设正式账号密码。在项目根目录的交互式终端运行：

```powershell
Set-Location <PROJECT_ROOT>
.\.venv\Scripts\python.exe -m scripts.init_admin
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

依次输入用户名、密码、确认密码，输入均不回显。用户名 3～50 字符，密码 15～128 字符，沿用现有弱密码检查。工具不从命令行参数、环境变量或管道读取凭据；无法保证隐藏输入时拒绝继续。

工具只创建一个新管理员，不提升已有账号；存在任何管理员（包括停用的管理员）时拒绝重复初始化。创建账号和初始化审计在同一个事务中提交，并发初始化也只能成功一次。需要更换管理员、恢复遗失的管理员密码，属于后续功能。

如果原服务仍在运行，请停止旧进程后重新启动；避免同时启动两个占用 8000 端口的服务。

## 权限与接口

所有管理员接口都使用 `get_current_admin`：先验证 JWT 签名、有效期、用户存在、实时启用状态及凭证版本，再从数据库读取角色。JWT 或请求中的 `role` 不能作为授权依据。

| 方法和路径 | 功能 |
| --- | --- |
| `GET /admin/users` | 用户分页；`page` 默认 1、`page_size` 默认 20（最大 100）；`search` 用户名子串搜索；`role=user/admin`；`is_active=true/false` |
| `GET /admin/users/{id}` | 安全用户元数据及资料、知识点、题目、作答、复习、问答、教练会话统计 |
| `PATCH /admin/users/{id}/status` | JSON `{"is_active": false}` 或 `true`；仅接受严格布尔值及此字段 |
| `GET /admin/stats` | 用户总数、启停数量、管理员数、近 30 天学习用户、资料数、题目数、首次答题次数 |
| `GET /admin/audit-logs` | 管理操作日志分页，参数 `page`、`page_size` |

`GET /auth/me` 新增 `role`、`is_active`。登录 JWT 新增 `ver`，旧版本 JWT 按版本 0 兼容，第一次状态变更后失效。注册仅接受用户名和密码，禁止附加角色、状态或凭证版本；请求查询参数不会提升权限。

未认证返回 401，普通用户访问管理员路由返回 403，停用自己或最后一个有效管理员返回 409，不存在的目标返回 404，非法参数返回 422。

状态变更使用 SQLite `BEGIN IMMEDIATE` 串行检查并写入，防止两名管理员同时停用对方而清空有效管理员。锁内再次核对操作者身份和版本，账号变更与日志一起提交；审计写入失败时账号变更也回滚。重复相同状态返回当前状态，并记录 `unchanged`，不重复增加凭证版本。

停用后登录及所有依赖 `get_current_user` 的新请求均返回 401，旧 JWT 无法继续使用；重新启用不会恢复旧 JWT，需要重新登录。已经通过认证并开始执行的请求不会被追溯中止。

管理员接口使用字段白名单及 `Cache-Control: no-store, private`，不返回密码哈希、Token、API Key、资料标题/全文、题干、问答或教练对话正文。

近 30 天学习用户按首次答题、错题复习、问答或学习记录中的用户 ID 去重；它表示学习活动人数，不表示在线人数或最近登录人数。无作答时正确率为 NULL，有作答但全错为 0%。

## 前端与手动验证

访问 `http://127.0.0.1:8000/app`，必要时 Ctrl+F5 刷新。普通账号没有“管理后台”入口；管理员身份由 `/auth/me` 确认后显示侧栏入口，手机通过导航菜单进入。

页面提供六项概览、用户搜索、角色和状态筛选、分页、统计详情、启停确认、审计分页以及加载/空状态/异常重试。详情仅展示元数据及统计。退出登录清空管理员缓存并忽略旧请求结果；API 返回 403 时清理页面并返回首页。

建议按以下顺序验证：

1. 普通账号登录，确认入口不可见；直接携带普通 JWT 调用 `/admin/stats`，应为 403；无 JWT 应为 401。
2. 管理员登录，搜索普通用户、筛选状态、切换分页并打开详情。
3. 点击停用，先取消一次，再确认；检查用户状态与日志同步刷新。
4. 在另一浏览器使用该普通用户原有会话访问资料/学习接口，应为 401；再次登录也应失败。
5. 管理员重新启用该用户，原会话仍失败，重新登录后可学习；原学习数据、XP 保留。
6. 管理员自身的停用按钮禁用；直接 PATCH 自身状态应返回 409，并产生拒绝操作审计。

## 自动化测试与实际结果

所有后端权限测试使用独立内存库；迁移、备份与并发测试使用临时文件库。浏览器验证启动独立临时数据库服务，凭据运行时随机生成，不写入正式用户数据，不调用付费模型。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Get-ChildItem tests/frontend*.mjs | ForEach-Object {
  node --experimental-vm-modules $_.FullName
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

测试覆盖未登录/普通用户拒绝、真实 JWT、禁用与重启用、注册提权阻断、伪造角色、管理员自我保护与最后管理员保护、审计原子性、重复操作、并发管理/初始化、CLI 不回显输入、历史库迁移与备份保真，以及原有学习/RAG/练习/XP/教练和自适应功能回归。

本次实际执行：后端完整回归 **157 项通过，0 失败**（21.228 秒）；前端五个自动化脚本全部通过；修改的 Python 文件 Ruff 检查通过。Node 的 VM Modules 实验提示以及教练测试 EventTarget 超过默认 10 个监听器的提示不影响断言结果，实际浏览器没有 JavaScript 错误。后端执行日志在 `.taste-skill/admin-backend-tests.txt`。

浏览器已验证 1440、768、390px：真实登录、导航、搜索、分页、隐私详情、取消/确认、启停、日志、退出以及普通用户的服务端 403；均无横向溢出。截图和报告位于 `.taste-skill/admin/`。视觉源码检查为 0 FAIL / 0 WARN，浏览器视觉规则检查为 0 FAIL，每个尺寸各有一个字号种类偏多的 WARN；本阶段保留原系统的排版尺度，未扩大为全站样式调整。

## 修改文件

- 模型：`app/models/user.py`、`app/models/admin_audit_log.py`、`app/models/__init__.py`。
- 认证与权限：`app/core/dependencies.py`、`app/core/jwt.py`、`app/routers/auth.py`、`app/routers/user.py`、`app/schemas/user.py`。
- 管理员 API：`app/routers/admin.py`、`app/services/admin.py`、`app/schemas/admin.py`、`app/main.py`。
- 迁移与运维：`migrations/versions/0005_admin_rbac.py`、`migrations/env.py`、`scripts/init_admin.py`、`scripts/migrate_admin.py`、`.gitignore`。
- 前端：`frontend/admin.js`、`frontend/admin.css`、`frontend/core.js`、`frontend/app.js`、`frontend/index.html`。
- 测试：`tests/test_admin.py`、`tests/test_admin_concurrency.py`、`tests/test_admin_migration.py`、`tests/frontend_admin.mjs`；隔离浏览器验证脚本在 `.taste-skill/check-admin.mjs`、`.taste-skill/preview_admin.py`。

## 当前边界

未提供角色变更、密码重置、永久删除、多管理员邀请、MFA 或管理员密码找回。账号写事务专门适配当前 SQLite，迁移到其他数据库时需要替换并发锁策略。审计没有删除 API，但拥有数据库文件写权限的人仍能篡改数据，尚无外部防篡改存证或日志保留策略。

登录与令牌存储沿用现有系统，JWT 仍由浏览器 localStorage 保存。公网部署需要 HTTPS，并保护服务器 `.env`、数据库和备份文件；后续可增加管理端 MFA 与更细粒度权限。自动化回归对模型调用使用替身，未验证真实付费模型供应商的在线可用性。
