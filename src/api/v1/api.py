from fastapi import APIRouter
from src.api.v1 import keys, auth, bots, dashboard, market

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(keys.router, prefix="/keys", tags=["keys"])
api_router.include_router(bots.router, prefix="/bots", tags=["bots"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(market.router, prefix="/market", tags=["market"])
