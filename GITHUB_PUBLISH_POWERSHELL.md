# GitHub 首次发布：Windows PowerShell

本文件是供作者手动执行的操作说明。准备阶段没有运行下列 Git 暂存、提交、远端或推送命令。先完成 [人工确认清单](GITHUB_RELEASE_REVIEW.md)，再执行。源项目、原349文件快照都保留；只在一个全新的副本初始化 Git。

## 1. 确认许可与公开范围

确认代码归属及是否选择 MIT/Apache-2.0 等许可证；没有选择时不要标为“开源项目”。若决定增加 LICENSE，先在发布候选中加入并重新审查、更新清单，不能绕过清单校验。保留字体声明。[第三方说明](THIRD_PARTY_NOTICES.md)。

在 GitHub Settings → Emails 开启 Keep my email addresses private、Block command line pushes that expose my email；复制界面提供的完整 noreply 邮箱，不猜测格式。旧提交不会因新邮箱设置而改变。[官方邮箱说明](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address)。

## 2. 按清单复制到全新目录（不复制 .git）

需 Windows PowerShell 5.1+、Git 2.28+。在普通 PowerShell 中执行，建议新开终端。修改路径仅影响新副本。脚本拒绝已有目标目录，不删除或覆盖任何项目。

```powershell
$ErrorActionPreference = 'Stop'
$snapshot = (Resolve-Path -LiteralPath 'D:\ai\learning\FastAPI\ai_learning_system_v2\.s6-local\github-release-candidate').Path
$destination = [IO.Path]::GetFullPath((Read-Host '输入一个尚不存在的新发布目录的绝对路径'))
if (Test-Path -LiteralPath $destination) { throw '目标必须尚不存在；不要使用原项目目录' }
if ($destination.StartsWith($snapshot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '目标不能位于快照内部' }
$manifest = Get-Content -LiteralPath (Join-Path $snapshot 'RELEASE_MANIFEST.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.contains_git_history -ne $false) { throw '快照不符合无历史要求' }
$paths = @($manifest.files | ForEach-Object { $_.path }) + @('RELEASE_MANIFEST.json')
$actual = @(Get-ChildItem -LiteralPath $snapshot -File -Recurse -Force | ForEach-Object { $_.FullName.Substring($snapshot.Length + 1).Replace('\','/') })
if (@(Compare-Object ($paths | Sort-Object) ($actual | Sort-Object)).Count -ne 0) { throw '候选文件集合发生变化，须重新审查' }
foreach ($item in $manifest.files) {
    if ([IO.Path]::IsPathRooted($item.path) -or $item.path -match '(^|[/\\])\.\.([/\\]|$)|(^|[/\\])\.git([/\\]|$)|:') { throw '清单路径不安全' }
    $file = Join-Path $snapshot $item.path
    if ((Get-Item -LiteralPath $file).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '拒绝链接文件' }
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) { throw ('哈希不符: ' + $item.path) }
}
New-Item -ItemType Directory -Path $destination | Out-Null
foreach ($path in $paths) {
    $target = Join-Path $destination $path
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath (Join-Path $snapshot $path) -Destination $target
}
foreach ($item in $manifest.files) {
    if ((Get-FileHash -LiteralPath (Join-Path $destination $item.path) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) { throw ('复制后哈希不符: ' + $item.path) }
}
Set-Location -LiteralPath $destination
if (Test-Path -LiteralPath '.git') { throw '不得包含旧 Git 目录' }
Write-Host ('已复制 ' + $paths.Count + ' 个文件；尚未初始化 Git')
```

打开复制后的 README、架构图、七张截图和 docs/release/public-files.txt 逐项复核。发布副本仍不包含运行所需的真实密钥/数据库。不要再从原目录整包补文件，也不要使用 git clone --mirror、推送原 main 或复制原 .git。

## 3. 在新目录设置公开身份并创建首次提交

以下会修改**新副本**的本地 Git 配置与暂存区；只在作者确认后手动执行。没有全局配置命令。

```powershell
# 沿用上一段的 $destination、$manifest、$paths
if ((Get-Location).Path -ne $destination -or (Test-Path -LiteralPath '.git')) { throw '必须位于尚未初始化的新发布目录' }
$gitOverrides = @(Get-ChildItem Env: | Where-Object { $_.Name -match '^GIT_(DIR|WORK_TREE|INDEX_FILE|AUTHOR_.*|COMMITTER_.*|CONFIG.*)$' })
if ($gitOverrides.Count -gt 0) { throw '当前会话存在 Git 覆盖变量；请在清理这些覆盖变量的新终端重新操作' }
$publicName = Read-Host '输入希望公开显示的 Git 作者名'
$publicEmail = Read-Host '粘贴 GitHub Settings / Emails 的完整 noreply 邮箱'
if ([string]::IsNullOrWhiteSpace($publicName) -or $publicEmail -notmatch '^[^\s<>]+@users\.noreply\.github\.com$') { throw '公开身份无效' }
git init -b main
if ($LASTEXITCODE -ne 0) { throw 'git init 失败' }
git config --local user.name $publicName
git config --local user.email $publicEmail
git config --local user.useConfigOnly true
git config --local core.autocrlf false
# 如原全局开启提交签名，请另检查签名证书是否含私人邮箱；此处不修改签名策略。
$authorIdentity = git var GIT_AUTHOR_IDENT
$committerIdentity = git var GIT_COMMITTER_IDENT
if ($authorIdentity -notlike "*<$publicEmail>*" -or $committerIdentity -notlike "*<$publicEmail>*") { throw '实际作者或提交者邮箱与指定 noreply 不一致' }
# 清单逐项暂存，包含两个点号开头的环境示例；不对原项目 git add .
foreach ($path in $paths) {
    git --literal-pathspecs add -- $path
    if ($LASTEXITCODE -ne 0) { throw ('暂存失败: ' + $path) }
}
$staged = @(git ls-files)
if (@(Compare-Object ($paths | Sort-Object) ($staged | Sort-Object)).Count -ne 0) { throw '暂存文件与清单不一致' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw '暂存区格式检查失败' }
git diff --cached --stat
git status --short
# 在终端逐文件核对完后，再单独执行下一行。
git commit -m 'Initial portfolio source snapshot (S1-S6)'
if ($LASTEXITCODE -ne 0) { throw '首次提交失败' }
if ((git rev-list --count HEAD) -ne '1') { throw '预期只有一个新的根提交' }
git log -1 --format='Author: %an <%ae>%nCommitter: %cn <%ce>%nSubject: %s'
git status --short
```

原开发历史保留在本机，不伪造阶段提交或旧日期。README/S2～S6报告记录开发与验证过程。新仓库不会自动携带旧提交对象、邮箱、分支、标签、reflog 或远端，但公开文本仍可能含身份信息，必须独立审查。

## 4. 手动创建空的 GitHub 仓库，再推送

在 GitHub 网页创建**新的空仓库**，建议先 Private，名称例如 `zhixing-ai-learning-system`；不要自动勾选 README、.gitignore 或 LICENSE，以免产生无关初始历史。随后复制 HTTPS 地址，不在 URL 中附带 Token。使用 Git Credential Manager 的浏览器认证，不把凭据写入命令或远端 URL。[官方首次上传流程](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)。

```powershell
# 仍在新发布目录；以下是作者手动执行的真实上传动作。
$remoteUrl = Read-Host '粘贴新建空仓库的 HTTPS 地址'
if ($remoteUrl -notmatch '^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git$') { throw '请使用不含凭据的 github.com HTTPS 仓库地址' }
git remote add origin $remoteUrl
if ($LASTEXITCODE -ne 0) { throw '配置远端失败' }
git remote -v
git push -u origin main
if ($LASTEXITCODE -ne 0) { throw '推送失败；不要使用 --force' }
```

先在私有仓库检查：仅一个新根提交、作者与提交者为 noreply、README 图和链接正常、文件列表一致、无真实环境文件/DB/研究数据、第三方声明齐全。再按 PORTFOLIO_DEMO.md 在**另一克隆目录**运行测试和本地替身演示，确认数据库迁移和容器启动。不要在发布文件夹生成运行数据后重新“全选上传”。

确认可见性、许可证和全部权利后，由作者在 Settings → General → Danger Zone 调整为 Public。公开后的 clone/fork 无法保证撤回。仓库 About 可写：“FastAPI + RAG + 受限工具学习教练 + 可解释自适应学习；JWT/RBAC；可复现本地 Docker 与离线评估。”避免使用“99%回答准确率”“已验证真人学习提升”等表述。

## 5. 未来更新

私有环境、数据库、备份、账号和研究文件继续留在原工作区。每次从白名单准备新的候选并复核 diff、素材权利和文件哈希后，才更新公开仓库。别把本轮 RELEASE_MANIFEST 当作未来任意改动都已获批准；新增 LICENSE 或改代码后须更新清单。上传说明中的 Git 命令不自动执行。
