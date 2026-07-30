from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.schemas import WalletOperation, WalletResponse
from app import services

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.post("/{customer_id}/credit", response_model=WalletResponse)
def credit_wallet(customer_id: str, operation: WalletOperation, db: Session = Depends(get_db)):
    """Credit amount to customer wallet."""
    wallet = services.credit_wallet(db, customer_id, operation.amount)
    return WalletResponse(customer_id=wallet.customer_id, balance=float(wallet.balance))


@router.post("/{customer_id}/debit", response_model=WalletResponse)
def debit_wallet(customer_id: str, operation: WalletOperation, db: Session = Depends(get_db)):
    """Debit amount from customer wallet."""
    try:
        wallet = services.debit_wallet(db, customer_id, operation.amount)
        return WalletResponse(customer_id=wallet.customer_id, balance=float(wallet.balance))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{customer_id}", response_model=WalletResponse)
def get_wallet(customer_id: str, db: Session = Depends(get_db)):
    """Get wallet balance for a customer."""
    wallet = services.get_wallet(db, customer_id)
    return WalletResponse(customer_id=wallet.customer_id, balance=float(wallet.balance))
