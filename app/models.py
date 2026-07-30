from sqlalchemy import Column, String, Numeric, DateTime, CheckConstraint, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    
    user_id = Column(String(100), primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(String(10), default="true")
    
    # Relationships
    orders = relationship("Order", back_populates="user")
    wallet = relationship("Wallet", back_populates="user", uselist=False)


class Order(Base):
    __tablename__ = "orders"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(String(100), ForeignKey('users.user_id'), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(10), nullable=False)
    idempotency_key = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="created")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="orders")
    
    __table_args__ = (
        CheckConstraint('amount > 0', name='check_order_amount_positive'),
    )


class Wallet(Base):
    __tablename__ = "wallets"
    
    customer_id = Column(String(100), ForeignKey('users.user_id'), primary_key=True)
    balance = Column(Numeric(10, 2), nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="wallet")
    
    __table_args__ = (
        CheckConstraint('balance >= 0', name='check_wallet_balance_non_negative'),
    )
