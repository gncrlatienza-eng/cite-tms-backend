from typing import Optional, Dict, Any
from fastapi import HTTPException, status
from datetime import datetime
from app.database import get_supabase, get_supabase_admin
from app.models.auth import UserCreate, UserLogin, UserResponse, Token, PasswordChange
from app.utils.auth import ( verify_password, get_password_hash, create_access_token, create_refresh_token, verify_token)


class AuthService:
    """Authentication service for user management"""
    
    @staticmethod
    async def register_user(user_data: UserCreate) -> Dict[str, Any]:
        """Register a new user"""
        supabase = get_supabase_admin()
        
        # ✅ ADD THIS BLOCK --- domain restriction
        if not user_data.email.endswith("@dlsl.edu.ph"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only @dlsl.edu.ph email addresses are allowed"
            )
        # ✅ END OF ADDED BLOCK
        
        # Check if user already exists
        existing_user = supabase.table("users").select("*").eq("email", user_data.email).execute()
        
        if existing_user.data and len(existing_user.data) > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Check if student ID already exists (for students)
        if user_data.student_id:
            existing_student = supabase.table("users").select("*").eq("student_id", user_data.student_id).execute()
            if existing_student.data and len(existing_student.data) > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Student ID already registered"
                )
        
        # Hash password
        hashed_password = get_password_hash(user_data.password)
        
        # Create user in database
        user_dict = user_data.model_dump(exclude={"password"})
        user_dict["password_hash"] = hashed_password
        user_dict["created_at"] = datetime.utcnow().isoformat()
        user_dict["is_active"] = True
        
        try:
            result = supabase.table("users").insert(user_dict).execute()
            
            if not result.data or len(result.data) == 0:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create user"
                )
            
            created_user = result.data[0]
            created_user.pop("password_hash", None)
            
            return {
                "message": "User registered successfully",
                "user": created_user
            }
        
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error creating user: {str(e)}"
            )
    
    @staticmethod
    async def login_user(login_data: UserLogin) -> Token:
        """Authenticate user and return tokens"""
        supabase = get_supabase()
        
        # Get user by email
        result = supabase.table("users").select("*").eq("email", login_data.email).execute()
        
        if not result.data or len(result.data) == 0:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        user = result.data[0]
        
        # Verify password
        if not verify_password(login_data.password, user.get("password_hash", "")):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Check if user is active
        if not user.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )
        
        # Create tokens
        token_data = {
            "sub": user["id"],
            "email": user["email"],
            "role": user["role"]
        }
        
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        
        # Update last login
        try:
            supabase.table("users").update({
                "last_login": datetime.utcnow().isoformat()
            }).eq("id", user["id"]).execute()
        except:
            pass
        
        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer"
        )
    
    @staticmethod
    async def refresh_access_token(refresh_token: str) -> Token:
        """Generate new access token from refresh token"""
        token_data = verify_token(refresh_token, token_type="refresh")
        
        if token_data is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
        supabase = get_supabase()
        result = supabase.table("users").select("*").eq("id", token_data.user_id).execute()
        
        if not result.data or len(result.data) == 0:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        user = result.data[0]
        
        if not user.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )
        
        new_token_data = {
            "sub": user["id"],
            "email": user["email"],
            "role": user["role"]
        }
        
        new_access_token = create_access_token(new_token_data)
        new_refresh_token = create_refresh_token(new_token_data)
        
        return Token(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer"
        )
    
    @staticmethod
    async def get_user_profile(user_id: str) -> Dict[str, Any]:
        """Get user profile by ID"""
        supabase = get_supabase()
        
        result = supabase.table("users").select("*").eq("id", user_id).execute()
        
        if not result.data or len(result.data) == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user = result.data[0]
        user.pop("password_hash", None)
        
        return user
    
    @staticmethod
    async def change_password(user_id: str, password_data: PasswordChange) -> Dict[str, str]:
        """Change user password"""
        supabase = get_supabase()
        
        result = supabase.table("users").select("*").eq("id", user_id).execute()
        
        if not result.data or len(result.data) == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user = result.data[0]
        
        if not verify_password(password_data.current_password, user.get("password_hash", "")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect"
            )
        
        new_password_hash = get_password_hash(password_data.new_password)
        
        try:
            supabase.table("users").update({
                "password_hash": new_password_hash,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", user_id).execute()
            
            return {"message": "Password changed successfully"}
        
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error changing password: {str(e)}"
            )