from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from app.models.auth import TokenData, UserRole
from app.utils.auth import verify_token
from app.database import get_supabase

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> TokenData:
    """Get current authenticated user from JWT token"""
    token = credentials.credentials
    
    token_data = verify_token(token, token_type="access")
    
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify user exists in database
    supabase = get_supabase()
    try:
        result = supabase.table("users").select("*").eq("id", token_data.user_id).execute()
        
        if not result.data or len(result.data) == 0:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        
        user = result.data[0]
        
        # Check if user is active
        if not user.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )
        
        return token_data
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )


async def get_current_active_user(
    current_user: TokenData = Depends(get_current_user)
) -> TokenData:
    """Get current active user"""
    return current_user


def require_role(allowed_roles: list[UserRole]):
    """Dependency to check if user has required role"""
    async def role_checker(current_user: TokenData = Depends(get_current_user)) -> TokenData:
        if current_user.role not in [role.value for role in allowed_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {[role.value for role in allowed_roles]}",
            )
        return current_user
    
    return role_checker


# Specific role dependencies
require_admin = require_role([UserRole.ADMIN])
require_faculty = require_role([UserRole.FACULTY, UserRole.ADMIN])
require_student = require_role([UserRole.STUDENT, UserRole.ADMIN])