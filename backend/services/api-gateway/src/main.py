import os
import httpx
import logging
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import json
import websockets
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="API Gateway", version="1.0.0")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3003", "http://localhost:3007", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 서비스 URL 설정
SERVICES = {
    "youtube_extractor": os.getenv("YOUTUBE_EXTRACTOR_URL", "http://youtube-extractor:8000"),
    "stt_processor": os.getenv("STT_PROCESSOR_URL", "http://stt-processor-api:8001"),
}

# Rate Limiting 미들웨어 (선택적 - 일단 주석 처리)
# from src.middleware import RateLimitMiddleware
# app.add_middleware(RateLimitMiddleware, calls=100, period=60)

# 인증 미들웨어 제거 (나중에 필요시 추가)
# from src.auth import verify_token

@app.get("/")
async def root():
    return {"message": "API Gateway is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "api-gateway"}

@app.post("/api/youtube/extract")
async def extract_audio(request: Request):  # verify_token 의존성 제거
    """YouTube 오디오 추출 프록시"""
    try:
        body = await request.json()
        logger.info(f"Proxying extract request to {SERVICES['youtube_extractor']}")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{SERVICES['youtube_extractor']}/extract",
                json=body
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"YouTube extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stt/transcribe")
async def request_transcription(request: Request):
    """STT 요청 프록시"""
    try:
        body = await request.json()
        logger.info(f"Proxying transcribe request to {SERVICES['stt_processor']}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{SERVICES['stt_processor']}/request_transcription",
                json=body
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"STT request failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/api/ws/{task_id}")
async def websocket_proxy(websocket: WebSocket, task_id: str):
    """WebSocket 프록시 - STT 서비스로 전달"""
    await websocket.accept()
    
    stt_ws_url = f"ws://stt-processor-api:8001/ws/{task_id}"
    logger.info(f"Proxying WebSocket for task {task_id} to {stt_ws_url}")
    
    try:
        # STT 서비스의 WebSocket에 연결
        logger.info(f"Attempting to connect to STT WebSocket: {stt_ws_url}")
        async with websockets.connect(stt_ws_url) as stt_ws:
            logger.info(f"Successfully connected to STT WebSocket for task {task_id}")
            # 양방향 메시지 전달
            async def forward_from_stt():
                """STT 서비스 -> 클라이언트"""
                try:
                    async for message in stt_ws:
                        logger.debug(f"Forwarding message from STT to client: {message[:100]}...")
                        await websocket.send_text(message)
                except websockets.exceptions.ConnectionClosed:
                    logger.info(f"STT WebSocket closed for task {task_id}")
                except Exception as e:
                    logger.error(f"Error forwarding from STT: {e}")
            
            async def forward_from_client():
                """클라이언트 -> STT 서비스 (일반적으로 없음)"""
                try:
                    while True:
                        data = await websocket.receive_text()
                        logger.debug(f"Forwarding message from client to STT: {data}")
                        await stt_ws.send(data)
                except Exception as e:
                    logger.debug(f"Client WebSocket closed: {e}")
            
            # 두 방향 동시 처리
            await asyncio.gather(
                forward_from_stt(),
                forward_from_client(),
                return_exceptions=True
            )
            
    except Exception as e:
        logger.error(f"WebSocket proxy error for task {task_id}: {e}")
        await websocket.send_json({
            "error": f"WebSocket proxy error: {str(e)}",
            "status": "FAILED"
        })
    finally:
        try:
            await websocket.close()
        except:
            pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)