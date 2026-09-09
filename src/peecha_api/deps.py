"""وابستگیِ مشترکِ FastAPI: استخراجِ (user_id, company_id) از توکنِ
Bearer -- نه از سشنِ سراسریِ peecha.session (که فقط برایِ اپِ دسکتاپِ
تک‌کاربره امن است، نه یک سرویسِ هم‌زمان‌چندکاربره)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, status

from peecha_api.security import decode_access_token


@dataclass
class AuthContext:
    user_id: int
    company_id: int


def get_current_context(authorization: str | None = Header(default=None)) -> AuthContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="توکنِ دسترسی لازم است.")
    token = authorization.removeprefix("Bearer ").strip()
    decoded = decode_access_token(token)
    if decoded is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="توکنِ دسترسی نامعتبر یا منقضی‌شده است.")
    user_id, company_id = decoded
    return AuthContext(user_id=user_id, company_id=company_id)
