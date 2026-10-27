"""Small SQLite transactions for administrative changes and one-time bootstrap."""
from fastapi import HTTPException
from sqlalchemy import func
from app.models import AdminAuditLog, User
from app.core.security import hash_password
from app.schemas.user import UserCreate


def begin_account_write(db):
    # Dependencies may have opened a read transaction. No pending writes are
    # allowed here. Acquire SQLite's write reservation before checking counts.
    db.rollback()
    if db.get_bind().dialect.name != "sqlite":
        raise RuntimeError("账号管理事务当前仅支持项目配置的 SQLite 数据库")
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def set_user_status(db, actor_id: int, actor_version: int, target_id: int, enabled: bool):
    begin_account_write(db)
    try:
        actor = db.get(User, actor_id)
        if actor is None or not actor.is_active or actor.auth_version != actor_version:
            raise HTTPException(401, "管理员登录已失效")
        if actor.role != "admin":
            raise HTTPException(403, "需要管理员权限")
        target = db.get(User, target_id)
        log = AdminAuditLog(actor_user_id=actor_id, target_user_id=target.id if target else None,
                            action="enable_user" if enabled else "disable_user", result="changed",
                            before_active=target.is_active if target else None,
                            after_active=enabled)
        denied = None
        if target is None:
            log.result = "not_found"
            denied = HTTPException(404, "用户不存在")
        elif not enabled and target.role == "admin" and target.is_active and db.query(func.count(User.id)).filter(
                User.role == "admin", User.is_active.is_(True)).scalar() <= 1:
            log.result = "denied_last_admin"
            denied = HTTPException(409, "不能停用最后一个有效管理员")
        elif not enabled and actor_id == target_id:
            log.result = "denied_self"
            denied = HTTPException(409, "不能停用自己的账号")
        elif target.is_active == enabled:
            log.result = "unchanged"
        else:
            target.is_active = enabled
            target.auth_version += 1
        if denied:
            log.after_active = log.before_active
        db.add(log)
        db.commit()  # Status and its audit record succeed or fail together.
        if denied:
            raise denied
        db.refresh(target)
        return target
    except Exception:
        db.rollback()
        raise


def bootstrap_admin(db, username: str, password: str):
    # Reuse registration validation; callers must never print validation inputs.
    request = UserCreate(username=username, password=password)
    password_digest = hash_password(request.password)
    begin_account_write(db)
    try:
        if db.query(User.id).filter(User.role == "admin").first() is not None:
            raise ValueError("管理员已初始化，不能重复运行")
        if db.query(User.id).filter(User.username == request.username).first() is not None:
            raise ValueError("用户名已存在；初始化不会提升已有账号权限，请使用新账号")
        admin = User(username=request.username, password_hash=password_digest, role="admin", is_active=True)
        db.add(admin); db.flush()
        db.add(AdminAuditLog(actor_user_id=admin.id, target_user_id=admin.id,
                            action="bootstrap_admin", result="created", after_active=True))
        db.commit()
        return admin.id
    except Exception:
        db.rollback()
        raise
