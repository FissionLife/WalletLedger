from fastapi import Request

from app.schemas import User


async def get_current_user(request: Request) -> User | None:
    """
    Placeholder for authentication logic.
    Currently returns None (no authentication enforced).
    """
    return None
