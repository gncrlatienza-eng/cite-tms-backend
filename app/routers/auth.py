from fastapi import APIRouter, Depends, status, HTTPException
from typing import Dict, Any
from app.models.auth import (
    UserCreate,
    UserLogin,
    UserResponse,
    Token,
    RefreshTokenRequest,
    PasswordChange,
    TokenData
)
from app.services.auth import AuthService
from app.middleware.auth import get_current_user, require_admin

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate):
    """Register a new user"""
    return await AuthService.register_user(user_data)


@router.post("/login", response_model=Token)
async def login(login_data: UserLogin):
    """Login with email and password"""
    return await AuthService.login_user(login_data)


@router.post("/refresh", response_model=Token)
async def refresh_token(token_request: RefreshTokenRequest):
    """Refresh access token using refresh token"""
    return await AuthService.refresh_access_token(token_request.refresh_token)


@router.get("/me", response_model=Dict[str, Any])
async def get_current_user_profile(current_user: TokenData = Depends(get_current_user)):
    """Get current authenticated user's profile"""
    return await AuthService.get_user_profile(current_user.user_id)


@router.post("/change-password")
async def change_password(
    password_data: PasswordChange,
    current_user: TokenData = Depends(get_current_user)
):
    """Change current user's password"""
    return await AuthService.change_password(current_user.user_id, password_data)


@router.post("/logout")
async def logout(current_user: TokenData = Depends(get_current_user)):
    """Logout current user"""
    return {
        "message": "Logged out successfully",
        "user_id": current_user.user_id
    }


@router.get("/users", dependencies=[Depends(require_admin)])
async def list_users():
    """List all users (Admin only)"""
    from app.database import get_supabase
    supabase = get_supabase()
    
    result = supabase.table("users").select("*").execute()
    
    users = result.data
    for user in users:
        user.pop("password_hash", None)
    
    return {
        "users": users,
        "total": len(users)
    }


@router.patch("/users/{user_id}/toggle-active", dependencies=[Depends(require_admin)])
async def toggle_user_active(user_id: str):
    """Toggle user active status (Admin only)"""
    from app.database import get_supabase
    from datetime import datetime
    
    supabase = get_supabase()
    
    result = supabase.table("users").select("*").eq("id", user_id).execute()
    
    if not result.data or len(result.data) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    user = result.data[0]
    new_status = not user.get("is_active", True)
    
    supabase.table("users").update({
        "is_active": new_status,
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", user_id).execute()
    
    return {
        "message": f"User {'activated' if new_status else 'deactivated'} successfully",
        "user_id": user_id,
        "is_active": new_status
    }