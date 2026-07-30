from fastapi import FastAPI
from app.db import init_db
from app.routes_users import router as users_router
from app.routes_orders import router as orders_router
from app.routes_wallet import router as wallet_router

app = FastAPI(title="Payment API", version="1.0.0")

app.include_router(users_router)
app.include_router(orders_router)
app.include_router(wallet_router)


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/")
def root():
    return {"message": "Payment API is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}
