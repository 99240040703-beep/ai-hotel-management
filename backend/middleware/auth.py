from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from utils.security import decode_access_token

try:
    from database import SessionLocal
    from models import User
except (ImportError, ValueError):
    from ..database import SessionLocal
    from ..models import User


security = HTTPBearer(auto_error=False)


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(request: Request):
    """
    Best-effort identity lookup.

    Returns None when there is no usable token, so public endpoints can
    stay public. Protected endpoints must use require_current_user
    instead of checking this by hand.
    """
    auth_header = request.headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.replace("Bearer ", "").strip()
    payload = decode_access_token(token)

    if not payload:
        return None

    user_id = payload.get("user_id") or payload.get("sub")

    if not user_id:
        return None

    # The account is re-read from the database on every request so a
    # deactivated user or a changed role takes effect immediately
    # instead of waiting for the token to expire.
    db = SessionLocal()

    try:
        user = db.query(User).filter(User.id == int(user_id)).first()

        if not user:
            return None

        return {
            "user_id": user.id,
            "user_name": user.name,
            "email": user.email,
            "role": user.role,
            "customer_id": user.customer_id,
            "active": bool(user.active),
            "loyalty_points": user.loyalty_points or 0,
        }
    finally:
        db.close()


async def require_current_user(request: Request):
    """Any signed-in, active account. Raises 401/403 otherwise."""
    user = await get_current_user(request)

    if not user:
        raise _unauthenticated()

    if not user["active"]:
        raise HTTPException(
            status_code=403,
            detail="This account has been deactivated",
        )

    return user


async def require_admin(request: Request):
    """Admin-only endpoints. Raises 401/403 otherwise."""
    user = await require_current_user(request)

    if user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )

    return user


async def require_customer(request: Request):
    """
    Customer-only endpoints.

    An admin signing in is still refused, so the customer surface cannot
    be reached with an admin token.
    """
    user = await require_current_user(request)

    if user["role"] != "customer":
        raise HTTPException(
            status_code=403,
            detail="Customer access required",
        )

    return user
