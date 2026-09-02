from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth_service import decode_access_token
from app.tenant_db import get_tenant_sessionmaker

_bearer_scheme = HTTPBearer()


async def get_current_tenant_db(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> AsyncSession:
    """Auth dependency for every admin endpoint: decodes the caller's JWT
    (issued by POST /api/v1/auth/login or /register) and yields a session
    connected straight to THAT tenant's own database — nothing else. There
    is no tenant_id filtering anywhere downstream because the connection
    itself is already scoped; a stolen/forged token for tenant A simply
    cannot reach tenant B's data no matter what ids it references.
    """
    try:
        payload = decode_access_token(credentials.credentials)
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    database_name = payload.get("database_name")
    if not database_name:
        raise HTTPException(status_code=401, detail="Malformed token")

    sessionmaker = get_tenant_sessionmaker(database_name)
    async with sessionmaker() as session:
        yield session


async def get_current_tenant_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> int:
    """Like get_current_tenant_db, but for the few endpoints (e.g. linking a
    Telegram bot token) that need to update the caller's own row in the
    registry DB itself, rather than connect to its per-tenant database.
    """
    try:
        payload = decode_access_token(credentials.credentials)
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Malformed token")
    return tenant_id
