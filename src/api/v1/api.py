from fastapi import APIRouter
from src.api.v1 import auth, bots, keys, dashboard

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(bots.router, prefix="/bots", tags=["Bots"])
api_router.include_router(keys.router, prefix="/keys", tags=["Keys"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
