import asyncio
import json
import logging
from typing import Dict, List

from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ConnectionManager:
    """
    WebSocket 连接管理器 (Hub)
    负责向前端推送：
    - 公共市场行情 (比如正在观察的币种涨跌)
    - 个人机器人的私有日志流和状态流
    """

    def __init__(self):
        # 维护基于 user_id 或会话的全部激活连接
        self.active_connections: Dict[int, List[WebSocket]] = {}
        # 专门针对大盘/行情看板的广播列表 (可不用登录也看到的公共连接)
        self.public_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket, user_id: int = None):
        """接入新的 WebSocket 并接受"""
        await websocket.accept()
        if user_id:
            if user_id not in self.active_connections:
                self.active_connections[user_id] = []
            self.active_connections[user_id].append(websocket)
        else:
            self.public_connections.append(websocket)
        logger.info(f"🟢 [WS Hub] 新连接入场. UserId: {user_id}")

    def disconnect(self, websocket: WebSocket, user_id: int = None):
        """下线断开清理资源"""
        if user_id and user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
        else:
            if websocket in self.public_connections:
                self.public_connections.remove(websocket)
        logger.info(f"🔌 [WS Hub] 连接已断开. UserId: {user_id}")

    async def send_personal_message(self, message: dict, user_id: int):
        """发送私有频道消息，常用于推送用户自己的网格交易买卖结果"""
        connections = self.active_connections.get(user_id, [])
        dead_sockets = []
        payload = json.dumps(message, ensure_ascii=False)
        for connection in connections:
            try:
                await connection.send_text(payload)
            except Exception:
                dead_sockets.append(connection)
                
        # 清理异常或断线的连接
        for d in dead_sockets:
            self.disconnect(d, user_id)

    async def broadcast(self, message: dict):
        """向所有连接广播消息，多用于全服广播熔断等极强提醒"""
        payload = json.dumps(message, ensure_ascii=False)
        # 1. 广播所有访客
        for connection in self.public_connections:
            await self._safe_send(connection, payload, user_id=None)
            
        # 2. 广播所有登录用户
        for user_id, connections in self.active_connections.items():
            for connection in connections:
                await self._safe_send(connection, payload, user_id=user_id)

    async def _safe_send(self, ws: WebSocket, msg: str, user_id: int = None):
        try:
            await ws.send_text(msg)
        except Exception:
            self.disconnect(ws, user_id=user_id)

# 暴露单例
ws_hub = ConnectionManager()
