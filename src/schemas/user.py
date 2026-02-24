from pydantic import BaseModel
from typing import Optional

class UserCreate(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenPayload(BaseModel):
    sub: Optional[str] = None
    is_admin: bool = False

class UserResponse(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_active: bool

    class Config:
        from_attributes = True

class TOTPVerify(BaseModel):
    token: str

class TOTPSetupResponse(BaseModel):
    secret: str
    qr_code_url: str
