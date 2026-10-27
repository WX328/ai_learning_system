# 第三方素材与分发说明

核对日期：2026-10-26。范围是源码候选及其中直接分发的素材；不是对全部代码来源或软件供应链的法律保证。项目自身尚未选择开源许可证，本文件不代替作者授权，也不把第三方素材改为项目许可证。

| 内容 | 核对结果 | 分发处理 |
| --- | --- | --- |
| frontend/fonts/ 下三个 Instrument Sans TTF | 字体 name 表包含 Instrument Sans 作者版权、1.000 版本及 OFL 链接；随附 OFL 与官方 master 的文本一致。当前字体与官方 master 完整 TTF 字节不同，不能声称是未经修改的同版原件。 | 保留 [OFL.txt](frontend/fonts/OFL.txt)，按 OFL-1.1 分发。官方 OFL 未列 Reserved Font Name；子集/修改版仍须保留声明、遵守命名条件，不能另改许可或单独售卖。没有替换字体。 |
| S3 九份论文 PDF | pypdf 检查仅发现嵌入的 DejaVu Sans 子集，没有 Windows 字体二进制。 | 补齐 [DEJAVU-LICENSE.txt](docs/licenses/DEJAVU-LICENSE.txt)，逐字复制自实际 Matplotlib 3.11.2 安装包附带声明，包括 Bitstream/Arev 条款。 |
| S3 SVG / PNG | SVG 仅引用 DejaVu Sans 名称；PNG 是绘图结果。数据、算法及局限标在图中。 | 保留三种格式的用途：网页矢量图、论文 PDF、通用 PNG；它们不是无用测试缓存。不得把合成图当真人实验。 |
| docs/portfolio/ 七张 PNG | S6 真实 Edge / 隔离服务 / 本地模型替身 / 合成账号与资料，0真人；PNG 只含 IHDR/IDAT/IEND，无文本/EXIF块。 | 保留一份展示图和来源清单，不分发重复截图。人工复看未见凭据或真实身份；[来源](docs/portfolio/README.md)。 |
| architecture.svg / demo-notes.txt | 项目内绘制的架构图与合成演示资料，无外部位图或原学习语料。 | 可作为候选；作者仍需确认自己的发布权利。 |
| frontend/icons.svg | 11个短 SVG symbol；未发现第三方包头或明确导入记录。形状相似不能证明来源。 | 作者确认是否来自教程或图标库；若有来源，保留对应许可/署名。没有冒用 Lucide 等项目的授权。 |
| S4 题库草案 | 文件逐题标为 ai_generated、pending_review，基于 Python 列表/字典语义，不是正式试卷。 | 保留草案来源和待审状态。作者审阅题干/答案及来源后才可用于真人研究；不能称已审核或保证原创。 |
| 旧 RAG 问句、notes、标签、逐题报告 | 由助手依据当时两份学习资料整理；候选内没有原始正文/向量，但未提供资料的来源授权台账。 | 精简候选暂缓13个相关文件；仅摘取数值汇总，不据“AI生成”推定可分发。原文件留在本机，确认权利后另行复核。 |
| Python 依赖 | 锁文件中的版本与当前安装元数据逐个核对；详见 [dependency-licenses.json](docs/release/dependency-licenses.json)。 | 源码快照不含 .venv、wheel、site-packages 或 vendored SDK；安装时各依赖保持自身许可。不是全依赖 MIT，包含 Apache、BSD、MPL-2.0、PSF及组合许可。 |
| Python/Debian、Nginx Docker 基础镜像 | Compose/Dockerfile 引用官方镜像，不在源码内分发镜像层。 | 本次只准备源码；若以后发布构建镜像/二进制包，需要另审镜像内全部组件、字体和通知，不能用本表代替。 |

依赖清单是安装元数据快照，不是漏洞扫描、完整 SBOM 或兼容性法律结论。可选 Matplotlib 依赖未严格锁定；复现原图以 figures.json 的3.11.2为准。没有发现大段明确标为复制的第三方源码或前端 vendor 包；静态扫描不能证明所有代码均原创。教程、学校/单位成果、协作者和 AI 辅助生成代码的发布权利仍由作者核实。

Windows 系统字体只在 CSS 回退或截图栅格化时使用，没有把微软雅黑/Segoe 字体文件加入快照。微软区分图像输出与字体文件的再分发，不应从操作系统复制字体充当 webfont。[微软字体说明](https://learn.microsoft.com/en-us/typography/fonts/font-faq)。

核对来源：[Instrument Sans 官方](https://github.com/Instrument/instrument-sans)、[官方 OFL](https://github.com/Instrument/instrument-sans/blob/master/OFL.txt)、[OFL FAQ](https://openfontlicense.org/ofl-faq/)、[DejaVu 许可](https://dejavu-fonts.github.io/License.html)、[Matplotlib 许可](https://matplotlib.org/stable/project/license.html)。

未选择许可证时不能把项目描述为已获开源使用授权。公开 GitHub 仓库仍允许平台规则下的查看和 fork；改回私有不会收回他人已保存的副本。[GitHub 许可说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)。
