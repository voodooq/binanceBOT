from src.api.v1 import keys, auth, bots, dashboard, market, ws, backtest, notifications

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(keys.router, prefix="/keys", tags=["keys"])
api_router.include_router(bots.router, prefix="/bots", tags=["bots"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(market.router, prefix="/market", tags=["market"])
api_router.include_router(backtest.router, prefix="/backtest", tags=["backtest"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.add_api_websocket_route("/ws", ws.websocket_endpoint)
