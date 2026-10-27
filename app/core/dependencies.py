import re

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.core.jwt import SECRET_KEY, ALGORITHM

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login"
)

def get_current_user(
        token:str = Depends(oauth2_scheme),
        db:Session = Depends(get_db)
):
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        user_id = payload.get("sub")

        if not isinstance(user_id, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", user_id):
            raise HTTPException(
                status_code=401,
                detail="无效的Token"
            )
        parsed_user_id = int(user_id)
        if parsed_user_id > 2**63 - 1:
            raise HTTPException(status_code=401, detail="无效的Token")

    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="无效的Token"
        )

    user = db.query(User).filter(
        User.id == parsed_user_id
    ).first()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="用户不存在"
        )

    version = payload.get("ver", 0)  # Pre-RBAC tokens remain valid until first revocation.
    if not user.is_active or type(version) is not int or version != user.auth_version:
        raise HTTPException(status_code=401, detail="账号已停用或登录已失效，请重新登录")

    return user


def get_current_admin(current_user: User = Depends(get_current_user)):
    # Roles in JWT/request data are never used as authority.
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user
