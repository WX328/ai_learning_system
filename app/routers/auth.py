from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.core.security import hash_password, verify_password
from app.core.jwt import create_access_token
from app.core.dependencies import get_current_user
from app.core.login_throttle import login_throttle

router = APIRouter(
    prefix="/auth",
    tags=["认证"]
)
DUMMY_PASSWORD_HASH = hash_password("unused-account-placeholder")

@router.post("/login")
def login(
    request: Request,
    form_data:OAuth2PasswordRequestForm = Depends(),
    db:Session = Depends(get_db)
):
    address = request.client.host if request.client else "unknown"
    username = form_data.username
    if len(username) > 50:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not login_throttle.allowed(username, address):
        raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试",
                            headers={"Retry-After": "60"})
    user = db.query(User).filter(
        User.username == username
    ).first()

    password_ok = verify_password(
        form_data.password, user.password_hash if user else DUMMY_PASSWORD_HASH
    )
    if not user or not password_ok or not user.is_active:
        login_throttle.failed(username, address)
        raise HTTPException(
            status_code=401,
            detail="用户名或密码错误"
        )

    login_throttle.succeeded(username)
    access_token = create_access_token(user.id, user.auth_version)

    return {
        "access_token":access_token,
        "token_type":"bearer"
    }

@router.get("/me")
def get_me(
    current_user:User = Depends(get_current_user)
):
    return {
        "id":current_user.id,
        "username":current_user.username,
        "role":current_user.role,
        "is_active":current_user.is_active,
    }
