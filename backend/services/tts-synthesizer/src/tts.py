import os
import collections
import torch

# ① RAdam 클래스를 안전하게 허용
import TTS.utils.radam
# ② defaultdict 클래스도 안전하게 허용
torch.serialization.add_safe_globals([
    TTS.utils.radam.RAdam,
    collections.defaultdict
])

# ③ TTS 클래스 임포트
from TTS.api import TTS as TTSAPI
from config.settings import TTS_MODEL_NAME

# ④ 모델 로드
tts_model = TTSAPI(model_name=TTS_MODEL_NAME)

def synthesize_and_save(text: str, filename: str = "output.wav") -> str:
    output_path = f"/app/src/{filename}"
    tts_model.tts_to_file(text=text, file_path=output_path)
    return output_path
