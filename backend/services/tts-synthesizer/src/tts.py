import os
import collections
import torch

# ① radam 모듈을 import (언피클링 안전 등록을 위해)
import TTS.utils.radam

# ② TTS API 클래스 import
from TTS.api import TTS as TTSAPI
from config.settings import TTS_MODEL_NAME

# 🔐 안전하게 허용할 글로벌 클래스들 등록
#    - RAdam: TTS 내부 optimizer
#    - defaultdict: 체크포인트 내부에 사용된 자료구조
#    - dict: 체크포인트 역직렬화 시 필요한 기본 dict 클래스
torch.serialization.add_safe_globals([
    TTS.utils.radam.RAdam,
    collections.defaultdict,
    dict
])

# 🔊 실제 사용할 TTS 모델 인스턴스 생성
tts_model = TTSAPI(model_name=TTS_MODEL_NAME)

def synthesize_and_save(text: str, filename: str = "output.wav") -> str:
    """
    주어진 텍스트(text)를 음성으로 변환하여 WAV 파일로 저장 후 경로 반환.
    파일은 /app/src/output.wav 형태로 저장됨.
    """
    output_path = os.path.join(os.getcwd(), "src", filename)
    tts_model.tts_to_file(text=text, file_path=output_path)
    return output_path
