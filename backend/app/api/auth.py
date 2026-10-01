"""Вход специалистов и управление пользователями."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, is_admin
from app.db import get_db
from app.models import User
from app.schemas import LoginIn, TokenOut, UserCreate, UserOut
from app.security import Principal, hash_password, make_token, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверное имя пользователя или пароль")
    token, expires = make_token(user.username, user.role, settings.auth_secret, settings.auth_token_ttl_minutes)
    return TokenOut(access_token=token, username=user.username, role=user.role, expires_at=expires)


@router.get("/auth/me")
def me(request: Request, principal: Principal = Depends(current_user)):
    return {"username": principal.username, "role": principal.role, "auth_enabled": request.app.state.settings.auth_enabled}


@router.get("/users", response_model=list[UserOut])
def list_users(_: Principal = Depends(is_admin), db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.username)))


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, _: Principal = Depends(is_admin), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь уже существует")
    user = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(user)
    db.commit()
    return user


@router.patch("/users/{username}", response_model=UserOut)
def update_user(username: str, active: bool | None = None, role: str | None = None,
                principal: Principal = Depends(is_admin), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if username == principal.username and active is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя отключить собственную учётную запись")
    if role is not None:
        if role not in ("viewer", "analyst", "admin"):
            raise HTTPException(422, "Неизвестная роль")
        user.role = role
    if active is not None:
        user.active = active
    db.commit()
    return user


def ensure_admin(db: Session, username: str, password: str) -> None:
    """Создаёт первого администратора, если пользователей ещё нет."""
    if db.scalar(select(User.id).limit(1)) is None:
        db.add(User(username=username, password_hash=hash_password(password), role="admin"))
        db.commit()
