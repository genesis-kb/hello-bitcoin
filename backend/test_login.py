import asyncio
from config import SECRET_KEY, ALGORITHM
from jose import jwt
from datetime import datetime, timedelta, timezone
from schemas import LoginRequest

def _create_token(data: dict, expires_delta: timedelta) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    # payload.setdefault("jti", uuid.uuid4().hex)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

print("done")
