import logging
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware # CORS 미들웨어 임포트 추가
from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, Any

from .extractor import YouTubeExtractor

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI 앱 초기화
app = FastAPI(title="YouTube Audio Extractor Service")

# --- CORS 미들웨어 설정 추가 ---
origins = [
    "http://localhost",
    "http://localhost:3000", # React 앱 실행 주소
    "http://localhost:3003", # STT Processor 앱 실행 주소
    # 필요시 다른 허용할 출처 추가
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,       # 허용할 출처 목록
    allow_credentials=True,      # 자격 증명(쿠키 등) 허용 여부
    allow_methods=["*"],         # 모든 HTTP 메소드 허용 (GET, POST, OPTIONS 등)
    allow_headers=["*"],         # 모든 HTTP 헤더 허용
)
# --- CORS 설정 끝 ---

# 입력 모델 정의
class YouTubeExtractionRequest(BaseModel):
    youtube_url: HttpUrl
    output_format: str = "wav"  # 'wav' 또는 'mp3'
    sample_rate: int = 16000
    channels: int = 1

# 응답 모델 정의
class YouTubeExtractionResponse(BaseModel):
    file_path: str
    duration: float
    video_info: Dict[str, Any]

# 추출기 인스턴스 생성
output_dir = os.getenv("OUTPUT_DIR", "./downloads")
extractor = YouTubeExtractor(output_dir=output_dir)

@app.post("/extract", response_model=YouTubeExtractionResponse)
async def extract_audio(request: YouTubeExtractionRequest):
    """
    YouTube URL에서 오디오를 추출하고 STT 모델에 적합한 형식으로 변환
    """
    try:
        # 추출기 설정 업데이트
        extractor.preferred_format = request.output_format
        extractor.sample_rate = request.sample_rate
        extractor.channels = request.channels
        
        # 오디오 추출
        audio_path, video_info = extractor.extract_audio(str(request.youtube_url))
        
        # 응답 준비
        duration = video_info.get('duration', 0) if video_info else 0
        
        return {
            "file_path": audio_path,
            "duration": duration,
            "video_info": video_info
        }
    
    except Exception as e:
        logger.error(f"오디오 추출 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/info")
async def get_video_info(youtube_url: HttpUrl):
    """
    YouTube 비디오 정보 가져오기 (다운로드 없음)
    """
    try:
        video_info = extractor.get_video_info(str(youtube_url))
        return video_info
    
    except Exception as e:
        logger.error(f"비디오 정보 가져오기 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    """컨테이너 헬스체크용 엔드포인트"""
    try:
        # 간단한 파일 시스템 체크(출력 디렉토리 존재 여부)
        os.makedirs(output_dir, exist_ok=True)
        return {"status": "healthy", "service": "youtube-extractor"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
