from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import User
from app.schemas.user import UserCreate
from app.core.security import hash_password

router = APIRouter(
    prefix="/users",
    tags=["用户"]
)

@router.post("")
def create_user(
    user:UserCreate,
    db:Session=Depends(get_db)
):
    existing_user = db.query(User).filter(
        User.username == user.username
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="用户名已存在"
        )
    new_user=User(
        username=user.username,
        password_hash=hash_password(user.password),
        role="user",
        is_active=True,
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(400, "用户名已存在") from exc
    db.refresh(new_user)

    return {
        "id":new_user.id,
        "username":new_user.username
    }
