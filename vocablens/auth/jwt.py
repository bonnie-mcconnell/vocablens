from datetime import datetime, timedelta
from jose import jwt, JWTError

from vocablens.config import settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


def create_access_token(user_id: int) -> str:

    now = datetime.utcnow()

    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> int:

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        return int(payload["sub"])

    except JWTError:
        raise ValueError("Invalid token")