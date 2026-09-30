import hmac
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_env
from app.models import utcnow

bearer = HTTPBearer(auto_error=False)


def check_credentials(email: str, password: str) -> bool:
    env = get_env()
    email_ok = hmac.compare_digest(email.strip().lower().encode(), env.admin_email.strip().lower().encode())
    password_ok = hmac.compare_digest(password.encode(), env.admin_password.encode())
    return email_ok and password_ok


def create_token() -> str:
    env = get_env()
    payload = {"sub": env.admin_email, "exp": utcnow() + timedelta(hours=env.token_ttl_hours)}
    return jwt.encode(payload, env.secret_key, algorithm="HS256")


def require_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        payload = jwt.decode(credentials.credentials, get_env().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, sign in again") from None
    return payload["sub"]
