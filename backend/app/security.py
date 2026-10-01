"""Аутентификация и роли: пароли PBKDF2-SHA256, подписанные HMAC токены доступа, API-ключ для приёма транзакций."""
import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

PBKDF2_ITERATIONS = 200_000
ROLE_LEVELS = {"viewer": 1, "analyst": 2, "admin": 3}


@dataclass(frozen=True)
class Principal:
    username: str
    role: str  # viewer | analyst | admin | service

    def allows(self, *roles: str) -> bool:
        return self.role in roles


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    return hmac.compare_digest(digest.hex(), digest_hex)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(username: str, role: str, secret: str, ttl_minutes: int) -> tuple[str, datetime]:
    expires = int(time.time()) + ttl_minutes * 60
    payload = _b64(json.dumps({"sub": username, "role": role, "exp": expires}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}", datetime.fromtimestamp(expires, timezone.utc)


def read_token(token: str, secret: str) -> Principal | None:
    """Проверяет подпись и срок действия. Возвращает None для недействительного токена."""
    try:
        payload, signature = token.split(".")
    except ValueError:
        return None
    expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(data.get("exp", 0)) < time.time() or data.get("role") not in ROLE_LEVELS:
        return None
    return Principal(username=str(data["sub"]), role=data["role"])
