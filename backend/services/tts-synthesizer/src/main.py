# import os
# import uuid
# import glob
# import time
# import torch
# from fastapi import FastAPI, Query, HTTPException
# from fastapi.responses import FileResponse
# from TTS.api import TTS
# from dotenv import load_dotenv

# # 환경 변수 로드
# load_dotenv()

# # 설정값
# AUDIO_DIR = os.getenv("AUDIO_DIR", "/tmp/tts-audio")
# CLEANUP_THRESHOLD = int(os.getenv("CLEANUP_THRESHOLD_SECONDS", "3600"))

# # Radam 직렬화 오류 방지
# torch.serialization.add_safe_globals([("TTS.utils.radam", "RAdam")])

# # FastAPI 앱 초기화
# app = FastAPI()

# # 오디오 디렉터리 보장
# os.makedirs(AUDIO_DIR, exist_ok=True)

# # 지원 언어별 모델 정보
# MODEL_MAP = {
#     "ja": {
#         "model_name": "tts_models/ja/kokoro/tacotron2-DDC",
#         "vocoder_name": "vocoder_models/ja/kokoro/hifigan_v1"
#     },
#     "ko": {
#         "model_name": "tts_models/multilingual/multi-dataset/xtts_v2",
#         "vocoder_name": "vocoder_models/multilingual/multi-dataset/hifigan_v2"
#     }
# }

# # 서버 시작 시 모델·보코더 한 번만 로드
# tts_engines = {
#     lang: TTS(model_name=info["model_name"], vocoder_path=info["vocoder_name"])
#     for lang, info in MODEL_MAP.items()
# }

# # 오래된 파일 정리 함수
# def cleanup_old_files():
#     now = time.time()
#     for path in glob.glob(f"{AUDIO_DIR}/*.wav"):
#         if now - os.path.getmtime(path) > CLEANUP_THRESHOLD:
#             try:
#                 os.remove(path)
#             except OSError:
#                 pass

# @app.get("/synthesize")
# def synthesize(text: str = Query(...), lang: str = Query(...)):
#     engine = tts_engines.get(lang)
#     if not engine:
#         raise HTTPException(status_code=400, detail=f"Language '{lang}' not supported.")

#     # 오래된 파일 정리
#     cleanup_old_files()

#     # 고유 파일명 생성
#     filename = f"{uuid.uuid4().hex}.wav"
#     output_path = os.path.join(AUDIO_DIR, filename)

#     # TTS 합성 및 저장
#     engine.tts_to_file(text=text, file_path=output_path)

#     # 합성된 파일 응답
#     return FileResponse(output_path, media_type="audio/wav", filename="output.wav")


import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from src.tts import synthesize_and_save

# FastAPI 앱 생성
app = FastAPI()

# CORS 설정 (프론트엔드가 localhost:3000 등에서 호출할 경우 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 필요 시 구체적인 도메인으로 제한 가능
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 요청 바디 스키마 정의
class TTSRequest(BaseModel):
    text: str

# POST /synthesize_audio 엔드포인트
@app.post("/synthesize_audio")
def synthesize_audio(req: TTSRequest):
    try:
        # 텍스트 받아서 output.wav로 저장
        output_path = synthesize_and_save(req.text, filename="output.wav")
        return {"audio_path": output_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# GET /audio/output.wav 로 WAV 파일 직접 다운로드/스트리밍
@app.get("/audio/output.wav")
def get_audio():
    audio_file = os.path.join(os.getcwd(), "src", "output.wav")
    if not os.path.isfile(audio_file):
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(audio_file, media_type="audio/wav")
