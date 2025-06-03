import os
from dotenv import load_dotenv

# .env 파일 로드 (현재 디렉토리가 config 폴더라고 가정하면, 한 단계 위에 .env가 위치)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# TTS 모델 및 Vocoder 모델 이름
TTS_MODEL_NAME = os.getenv("TTS_MODEL_NAME", "tts_models/ja/kokoro/tacotron2-DDC")
VOCODER_NAME = os.getenv("VOCODER_NAME", "vocoder_models/ja/kokoro/hifigan_v1")
