import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# TTS 모델 이름 (coqui TTS 레포지토리 내 모델 경로)
# 예: tts_models/ja/kokoro/tacotron2-DDC
TTS_MODEL_NAME = os.getenv("TTS_MODEL_NAME", "tts_models/ja/kokoro/tacotron2-DDC")
