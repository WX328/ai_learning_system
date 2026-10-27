"""One-time, terminal-only administrator initialization. No credential arguments."""
import getpass
import sys
import warnings

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from pydantic import ValidationError

from app.database import SessionLocal
from app.models import User
from app.services.admin import bootstrap_admin


def main():
    if not sys.stdin.isatty():
        print("请在交互式终端运行；不接受命令行、管道或环境变量中的管理员凭据。", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        current = set(MigrationContext.configure(db.connection()).get_current_heads())
        if current != set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads()):
            print("请先备份数据库并运行迁移。", file=sys.stderr)
            return 1
        if db.query(User.id).filter(User.role == "admin").first() is not None:
            print("管理员已初始化，不能重复运行。", file=sys.stderr)
            return 1
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                username = getpass.getpass("管理员用户名（输入不回显）：")
                password = getpass.getpass("管理员密码（至少 15 字符，输入不回显）：")
                if password != getpass.getpass("再次输入密码："):
                    print("两次密码不一致，未创建账号。", file=sys.stderr)
                    return 1
            bootstrap_admin(db, username, password)
        except ValidationError as exc:
            print("输入不符合要求：" + "；".join(e["msg"] for e in exc.errors(include_input=False)), file=sys.stderr)
            return 1
        except (ValueError, getpass.GetPassWarning):
            print("初始化未完成：输入终端不安全、用户名已存在或管理员已初始化。", file=sys.stderr)
            return 1
        except (EOFError, KeyboardInterrupt):
            print("初始化已取消，未创建账号。", file=sys.stderr)
            return 1
    print("管理员已创建，初始化操作已记录。请使用刚才设置的账号登录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
