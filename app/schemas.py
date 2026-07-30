from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime
from uuid import UUID


class UserCreate(BaseModel):
    user_id: str = Field(..., min_length=3, max_length=100, pattern=r'^[A-Z]+-\d+$')
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "CUST-001",
                "email": "customer@example.com",
                "full_name": "John Doe",
                "phone": "+91-9876543210"
            }
        }


class UserResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    phone: Optional[str]
    created_at: datetime
    is_active: str
    
    class Config:
        from_attributes = True


class UserDetail(BaseModel):
    user_id: str
    email: str
    full_name: str
    phone: Optional[str]
    created_at: datetime
    is_active: str
    
    class Config:
        from_attributes = True


class OrderCreate(BaseModel):
    customer_id: str = Field(..., min_length=3, max_length=100)
    amount: float = Field(..., gt=0, le=1000000)
    currency: str = Field(default="INR", pattern=r'^[A-Z]{3}$')
    idempotency_key: Optional[str] = Field(None, max_length=255)
    
    class Config:
        json_schema_extra = {
            "example": {
                "customer_id": "CUST-001",
                "amount": 499.99,
                "currency": "INR",
                "idempotency_key": "order-abc-123"
            }
        }


class OrderResponse(BaseModel):
    order_id: UUID
    status: str
    
    class Config:
        from_attributes = True


class OrderDetail(BaseModel):
    id: UUID
    customer_id: str
    amount: float
    currency: str
    status: str
    idempotency_key: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class WalletOperation(BaseModel):
    amount: float = Field(..., gt=0, le=100000)
    
    class Config:
        json_schema_extra = {
            "example": {
                "amount": 1000.00
            }
        }


class WalletResponse(BaseModel):
    customer_id: str
    balance: float
    
    class Config:
        from_attributes = True


class WalletDetail(BaseModel):
    customer_id: str
    balance: float
    updated_at: datetime
    
    class Config:
        from_attributes = True


class User(BaseModel):
    user_id: str
    username: str
