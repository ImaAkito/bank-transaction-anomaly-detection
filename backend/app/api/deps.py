import hmac
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status

from app.security import Principal, read_token
from app.services.pipeline import AnalysisService

ANONYMOUS_ADMIN = Principal(username="admin", role="admin")


def get_service(request: Request) -> AnalysisService:
    return request.app.state.service


def authenticate(request: Request, token: str | None = None) -> Principal | None:
    """Определяет пользователя по заголовку Authorization, параметру token (WebSocket) или X-API-Key."""
    settings = request.app.state.settings
    if not settings.auth_enabled:
        return ANONYMOUS_ADMIN
    api_key = request.headers.get("x-api-key")
    if api_key and settings.ingest_api_key and hmac.compare_digest(api_key, settings.ingest_api_key):
        return Principal(username="ingest-service", role="service")
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    if not token:
        return None
    return read_token(token, settings.auth_secret)


def current_user(request: Request) -> Principal:
    principal = authenticate(request)
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход", headers={"WWW-Authenticate": "Bearer"})
    return principal


def require_roles(*roles: str) -> Callable[[Principal], Principal]:
    def dependency(principal: Principal = Depends(current_user)) -> Principal:
        if not principal.allows(*roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return principal

    return dependency


can_read = require_roles("viewer", "analyst", "admin")
can_review = require_roles("analyst", "admin")
can_ingest = require_roles("service", "analyst", "admin")
is_admin = require_roles("admin")
