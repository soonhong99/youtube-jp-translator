import os
import uuid
import glob
import time
import torch
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse
from TTS.api import TTS
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

# 설정값
AUDIO_DIR = os.getenv("AUDIO_DIR", "/tmp/tts-audio")
CLEANUP_THRESHOLD = int(os.getenv("CLEANUP_THRESHOLD_SECONDS", "3600"))

# Radam 직렬화 오류 방지
torch.serialization.add_safe_globals([("TTS.utils.radam", "RAdam")])

# FastAPI 앱 초기화
app = FastAPI()

# 오디오 디렉터리 보장
os.makedirs(AUDIO_DIR, exist_ok=True)

# 지원 언어별 모델 정보
MODEL_MAP = {
    "ja": {
        "model_name": "tts_models/ja/kokoro/tacotron2-DDC",
        "vocoder_name": "vocoder_models/ja/kokoro/hifigan_v1"
    },
    "ko": {
        "model_name": "tts_models/multilingual/multi-dataset/xtts_v2",
        "vocoder_name": "vocoder_models/multilingual/multi-dataset/hifigan_v2"
    }
}

# 서버 시작 시 모델·보코더 한 번만 로드
tts_engines = {
    lang: TTS(model_name=info["model_name"], vocoder_path=info["vocoder_name"])
    for lang, info in MODEL_MAP.items()
}

# 오래된 파일 정리 함수
def cleanup_old_files():
    now = time.time()
    for path in glob.glob(f"{AUDIO_DIR}/*.wav"):
        if now - os.path.getmtime(path) > CLEANUP_THRESHOLD:
            try:
                os.remove(path)
            except OSError:
                pass

@app.get("/synthesize")
def synthesize(text: str = Query(...), lang: str = Query(...)):
    engine = tts_engines.get(lang)
    if not engine:
        raise HTTPException(status_code=400, detail=f"Language '{lang}' not supported.")

    # 오래된 파일 정리
    cleanup_old_files()

    # 고유 파일명 생성
    filename = f"{uuid.uuid4().hex}.wav"
    output_path = os.path.join(AUDIO_DIR, filename)

    # TTS 합성 및 저장
    engine.tts_to_file(text=text, file_path=output_path)

    # 합성된 파일 응답
    return FileResponse(output_path, media_type="audio/wav", filename="output.wav")
