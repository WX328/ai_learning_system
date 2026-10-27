# 手动检查脚本

这些脚本从旧版 `app/services/test_*.py` 移来。它们不是自动测试，部分会访问本地数据库或模型服务。请从项目根目录按需运行，例如 `python -m scripts.manual.demo_rag`。自动回归测试统一放在 `tests/`。
