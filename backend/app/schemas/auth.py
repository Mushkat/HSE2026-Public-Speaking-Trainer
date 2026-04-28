from pydantic import BaseModel, EmailStr, Field, field_validator
import re

PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,64}$")

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        if not PASSWORD_PATTERN.match(value):
            raise ValueError(
                "Password must be lowercase, uppercase, numeric "
                "and be 8-64 characters long"
            )

        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password after UTF-8 encoding cannot exceed 72 bytes")

        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: EmailStr
