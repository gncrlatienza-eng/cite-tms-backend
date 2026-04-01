from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from app.models.auth import TokenData, UserRole
from app.utils.auth import verify_token
from app.database import get_supabase
from jwt import PyJWKClient
import jwt
import os

security = HTTPBearer()


def _try_supabase_jwt(token: str) -> Optional[TokenData]:
    """Try to decode a Supabase-issued JWT and map it to TokenData."""
    try:
        supabase_url = os.environ.get("SUPABASE_URL")
        if not supabase_url:
            return None

        jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json"
        jwks_client = PyJWKClient(jwks_url)
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )

        supabase_user_id = payload.get("sub")
        if not supabase_user_id:
            return None

        # ── Use email lookup instead of id ────────────────────────────────────
        email = payload.get("email")
        if not email:
            return None

        supabase = get_supabase()
        result = (
            supabase.table("users")
            .select("*")
            .eq("email", email)  # ← fixed: look up by email not Supabase UUID
            .execute()
        )

        if not result.data:
            return None

        user = result.data[0]

        if not user.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )

        return TokenData(
            user_id=str(user["id"]),
            email=user.get("email"),
            role=user.get("role", UserRole.STUDENT.value),
        )

    except HTTPException:
        raise
    except Exception:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenData:
    """Accept either a FastAPI JWT or a Supabase OAuth JWT."""
    token = credentials.credentials

    # ── 1. Try your own FastAPI token first ──────────────────────────────────
    token_data = verify_token(token, token_type="access")

    if token_data is not None:
        supabase = get_supabase()
        try:
            result = (
                supabase.table("users")
                .select("*")
                .eq("id", token_data.user_id)
                .execute()
            )
            if not result.data:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found",
                )
            user = result.data[0]
            if not user.get("is_active", True):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User account is inactive",
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        return token_data

    # ── 2. Fall back to Supabase OAuth JWT (Google login) ────────────────────
    token_data = _try_supabase_jwt(token)

    if token_data is not None:
        return token_data

    # ── 3. Both failed ────────────────────────────────────────────────────────
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_active_user(
    current_user: TokenData = Depends(get_current_user),
) -> TokenData:
    return current_user


def require_role(allowed_roles: list[UserRole]):
    async def role_checker(
        current_user: TokenData = Depends(get_current_user),
    ) -> TokenData:
        if current_user.role not in [role.value for role in allowed_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {[role.value for role in allowed_roles]}",
            )
        return current_user

    return role_checker


require_admin = require_role([UserRole.ADMIN])
require_faculty = require_role([UserRole.FACULTY, UserRole.ADMIN])
require_student = require_role([UserRole.STUDENT, UserRole.ADMIN])