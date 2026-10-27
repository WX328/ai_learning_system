# 作品集图片来源

这7张 PNG 来自 2026-10-26 的 S6 独立 Docker 项目，由已有 Playwright 驱动真实 Microsoft Edge；后台为真实 FastAPI/JWT/SQLite，模型为本地 HTTP 替身。账号、资料、题目和操作均属工程演示，真实参与者0人。不得用截图中的分数、人数或反馈声称真人学习效果或真实供应商内容质量。

桌面视口1440×1000，手机390×844，截图为整页，因此实际高度可能更大；等待字体、地图节点和提示条自然消失后拍摄。无图像编辑、凭据遮盖或合成UI。逐张检查未见 API Key、密码、Token、真实个人身份或私人资料；可见 s5- 前缀的随机账号来自复用S5测试工具，数据仍是本次S6新建。

| 文件 | 展示内容 |
| --- | --- |
| practice-desktop.png | 答错后的规则掌握度、样本数、推荐解释和本地反馈 |
| map-desktop.png / map-mobile.png | 已加载的知识点、复习后的41分规则指数、未练习项 |
| rag-desktop.png | 资料范围、来源入口和替身回答 |
| coach-desktop.png | 持久化计划、当前学情和受限工具检索后的回复 |
| admin-desktop.png / admin-mobile.png | 合成账号停用、最小统计和操作审计 |

完整来源、尺寸、SHA256见 [screenshots.json](screenshots.json)；实际运行报告见 [browser/report.json](../../evaluation/reports/s6/browser/report.json)。原349文件候选的两份截图字节相同；本次精简发布仅保留本目录这一份，浏览器JSON报告仍保留。不要把本地调试目录的其他截图批量加入仓库。

[architecture.svg](architecture.svg) 是手写的代码原生矢量架构图，不依赖外部图片/字体或图像生成服务；文字描述对应当前实现。[demo-notes.txt](demo-notes.txt) 是可公开的合成演示资料。第三方字体的原有OFL声明保留在 frontend/fonts/OFL.txt；整个项目的开源许可证由作者另行确认。
