import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from src.core.config import settings

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动应用时：挂载跨进程熔断事件总线
    from src.engine.redis_pubsub import redis_bus
    await redis_bus.start()
    
    # [P4] 服务启动时持久化恢复所有 RUNNING 机器人
    from src.db.session import AsyncSessionLocal
    from src.engine.strategy_manager import strategy_manager
    async with AsyncSessionLocal() as db:
        await strategy_manager.init_and_resume_all(db)
    
    yield
    
    # 退出应用时：自动中止所有机器人的交易并注销总线
    from src.engine.strategy_manager import strategy_manager
    await strategy_manager.stop_all_bots()
    
    # [P4] 停止流聚合中心
    from src.engine.stream_aggregator import stream_aggregator
    await stream_aggregator.stop()
        
    await redis_bus.stop()

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        lifespan=lifespan
    )

    # Set all CORS enabled origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], # For development. In production, specify exact origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from src.api.v1.api import api_router
    app.include_router(api_router, prefix=settings.API_V1_STR)

    @app.get("/health", tags=["system"])
    async def health_check():
        return {"status": "ok", "version": settings.VERSION}

    return app

app = create_app()
