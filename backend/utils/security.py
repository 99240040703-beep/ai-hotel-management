from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import JWTError, jwt

from dotenv import load_dotenv
import os

load_dotenv()


# The signing key must be supplied by the environment. A hardcoded
# fallback would let anyone who has read the source mint valid tokens,
# so a missing key stops the process instead of silently degrading.
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()

if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. Add it to backend/.env, for example:\n"
        "    python -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "Restart the backend afterwards."
    )

ALGORITHM = os.getenv("ALGORITHM", "HS256")

try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
    )
except ValueError:
    ACCESS_TOKEN_EXPIRE_MINUTES = 1440


def create_access_token(
    data: dict,
    expires_delta: timedelta = None,
) -> str:
    """
    Builds a signed JWT.

    Adds the standard claims on top of the caller's payload:
      sub - the user id, so a token is bound to exactly one account
      jti - a unique token id, so individual tokens can be revoked
      iat / exp - issued-at and expiry
    """
    to_encode = data.copy()

    issued_at = datetime.now(timezone.utc)

    to_encode.update(
        {
            "sub": str(to_encode.get("user_id", "")),
            "jti": uuid4().hex,
            "iat": issued_at,
            "exp": issued_at
            + (
                expires_delta
                or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            ),
        }
    )

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str):
    """Returns the token payload, or None when it is invalid/expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        return payload
    except JWTError:
        return None
