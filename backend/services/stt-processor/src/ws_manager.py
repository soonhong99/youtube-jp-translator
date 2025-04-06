import logging
from typing import Dict
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # 활성 연결 저장: {task_id: WebSocket 객체}
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        self.active_connections[task_id] = websocket
        logger.info(f"WebSocket client connected for task_id: {task_id}")

    def disconnect(self, task_id: str):
        if task_id in self.active_connections:
            del self.active_connections[task_id]
            logger.info(f"WebSocket client disconnected for task_id: {task_id}")

    async def send_json_message(self, task_id: str, message: dict):
        """특정 Task ID의 WebSocket 클라이언트에게 JSON 메시지 전송"""
        if task_id in self.active_connections:
            websocket = self.active_connections[task_id]
            try:
                await websocket.send_json(message)
                logger.debug(f"WS message sent to {task_id}: {message}")
            except WebSocketDisconnect:
                logger.warning(f"WS client for {task_id} disconnected before message could be sent.")
                self.disconnect(task_id)
            except RuntimeError as e:
                 if "Cannot call 'send' once a close message has been sent" in str(e):
                       logger.warning(f"Attempted to send message to already closed WS for {task_id}.")
                       self.disconnect(task_id)
                 else:
                      logger.error(f"Runtime error sending WS message to {task_id}: {e}", exc_info=True)
                      self.disconnect(task_id)
            except Exception as e:
                logger.error(f"Error sending WS message to {task_id}: {e}", exc_info=True)
                self.disconnect(task_id)
        else:
            logger.warning(f"No active WebSocket connection found for task_id: {task_id} to send message.")

# 전역 관리자 인스턴스 생성
manager = ConnectionManager()