from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from src.engine.ws_hub import ws_hub
from src.core.security import decode_access_token
from src.schemas.user import TokenPayload
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.websocket("/")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None)
):
    """
    通用 WebSocket 挂载点。
    支持鉴权（通过 Query 参数传 Token）。
    接入后由 ws_hub 统一管理推送。
    """
    user_id = None
    if token:
        try:
            payload = decode_access_token(token)
            if payload:
                token_data = TokenPayload(**payload)
                user_id = int(token_data.sub)
        except Exception as e:
            logger.warning(f"WS Auth failed: {e}")
            # 对于公共看板，我们可以允许未登录访问，或者直接关闭
            # 这里我们选择允许连接，但 user_id 为 None (进入 public_connections)
    
    await ws_hub.connect(websocket, user_id=user_id)
    
    try:
        while True:
            # 持续监听客户端发来的消息 (比如前端可能发心跳或指令)
            data = await websocket.receive_text()
            # 目前仅作为推送中心，不处理业务指令
            pass
    except WebSocketDisconnect:
        ws_hub.disconnect(websocket, user_id=user_id)
    except Exception as e:
        logger.error(f"WS Error: {e}")
        ws_hub.disconnect(websocket, user_id=user_id)
