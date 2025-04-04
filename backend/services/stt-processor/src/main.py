import logging
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, Field
from typing import Union, List, Dict, Any

# stt.py 에서 STT 함수 임포트
from .stt import transcribe_audio_file, transcribe_audio_file_with_timestamps, stt_model

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title="STT Processor Service",
    description="Transcribes audio files using Faster-Whisper.",
    version="0.1.0"
)

# --- API 요청/응답 모델 정의 ---
class STTRequest(BaseModel):
    # youtube-extractor가 저장한 WAV 파일의 *컨테이너 내부* 경로를 받습니다.
    wav_file_path: str = Field(..., description="Absolute path to the WAV file inside the STT container.")
    language: str = Field("ja", description="Language code for transcription (e.g., 'ja', 'en').")

class STTResponse(BaseModel):
    text: str = Field(..., description="The transcribed text.")

class Segment(BaseModel):
    start: float
    end: float
    text: str

class STTResponseWithTimestamps(BaseModel):
    segments: List[Segment] = Field(..., description="List of transcribed segments with timestamps.")

# --- API 엔드포인트 ---
@app.post("/transcribe", response_model=STTResponse, summary="Transcribe audio to text")
async def transcribe_endpoint(request: STTRequest):
    """
    Receives the path to a WAV file and returns the transcribed text.
    The path must be accessible from within the STT service container.
    """
    try:
        logger.info(f"Received /transcribe request for: {request.wav_file_path}")
        # stt.py의 함수 호출
        transcribed_text = transcribe_audio_file(request.wav_file_path, request.language)
        return {"text": transcribed_text}
    except FileNotFoundError as e:
        logger.error(f"File not found error: {e}")
        raise HTTPException(status_code=404, detail=f"Audio file not found at the specified path: {request.wav_file_path}")
    except RuntimeError as e: # 모델 로드 실패 등
        logger.error(f"Runtime error: {e}")
        raise HTTPException(status_code=503, detail=f"STT Service error: {e}") # 503 Service Unavailable
    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error during transcription: {e}")

@app.post("/transcribe_timestamps", response_model=STTResponseWithTimestamps, summary="Transcribe audio with timestamps")
async def transcribe_timestamps_endpoint(request: STTRequest):
    """
    Receives the path to a WAV file and returns transcribed segments with timestamps.
    """
    try:
        logger.info(f"Received /transcribe_timestamps request for: {request.wav_file_path}")
        segments = transcribe_audio_file_with_timestamps(request.wav_file_path, request.language)
        return {"segments": segments}
    except FileNotFoundError as e:
        logger.error(f"File not found error: {e}")
        raise HTTPException(status_code=404, detail=f"Audio file not found: {request.wav_file_path}")
    except RuntimeError as e:
        logger.error(f"Runtime error: {e}")
        raise HTTPException(status_code=503, detail=f"STT Service error: {e}")
    except Exception as e:
        logger.error(f"Transcription with timestamps failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error during timestamped transcription: {e}")


@app.get("/health", summary="Health check")
async def health_check():
    """
    Checks if the STT service and model are ready.
    """
    if stt_model:
        return {"status": "ok", "message": "STT model is loaded and service is running."}
    else:
        logger.warning("Health check failed: STT model not loaded.")
        # 모델 로드 실패 시 503 Service Unavailable 반환
        raise HTTPException(status_code=503, detail="STT model is not loaded.")

# uvicorn 직접 실행 시 (개발용)
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8001)