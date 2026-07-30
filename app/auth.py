from fastapi import Request
from typing import Optional
from app.schemas import User


async def get_current_user(request: Request) -> Optional[User]:
    """
    Placeholder for authentication logic.
    Currently returns None (no authentication enforced).
    """
    return None
