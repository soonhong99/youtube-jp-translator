# import os
# import collections
# import torch

# # ① radam 모듈 import (언피클링 안전 등록)
# import TTS.utils.radam

# # ② 환경변수로부터 모델 이름 읽기
# from config.settings import TTS_MODEL_NAME, VOCODER_NAME

# # ③ TTS API 클래스 import (별칭 TTSAPI)
# from TTS.api import TTS as TTSAPI

# # 🔐 안전하게 허용할 글로벌 클래스들 등록
# torch.serialization.add_safe_globals([
#     TTS.utils.radam.RAdam,
#     collections.defaultdict,
#     dict
# ])

# # 🔊 Tacotron2 + HiFi-GAN 모델을 한 번만 로드
# tts_model = TTSAPI(
#     model_name=TTS_MODEL_NAME,
#     vocoder_name=VOCODER_NAME,
#     # use_cuda=False    # GPU 사용 시 True로 바꿀 수 있습니다.
# )

# def synthesize_and_save(text: str) -> bytes:
#     """
#     주어진 일본어 텍스트(text)를 합성하여 WAV 바이너리(Bytes)로 반환.
#     - tts_model.tts()가 반환하는 NumPy 배열을 soundfile로 WAV로 씁니다.
#     """
#     # 1) 텍스트 → 음성(NumPy array) 생성
#     wav_array = tts_model.tts(text, speaker=None, language="ja")

#     # 2) NumPy array → WAV 바이트 스트림
#     import io, soundfile as sf
#     buffer = io.BytesIO()
#     sample_rate = tts_model.synthesizer.output_sample_rate
#     sf.write(buffer, wav_array, sample_rate, format="WAV")
#     buffer.seek(0)
#     return buffer.read()

# backend/services/tts-synthesizer/src/tts.py

import os
import io
import torch
import collections
from TTS.utils.radam import RAdam
from TTS.api import TTS
import soundfile as sf

# ───── 언피클러 안전 목록에 필요한 클래스들 등록 ──────────────────────
torch.serialization.add_safe_globals([
    RAdam,
    collections.defaultdict,
    dict,
])
# ──────────────────────────────────────────────────────────────

# 환경 변수에서 모델 이름을 읽거나 기본값으로 지정
TTS_MODEL_NAME = os.getenv("MODEL_NAME", "tts_models/ja/kokoro/tacotron2-DDC")
# VOCODER_MODEL_NAME = os.getenv("VOCODER_NAME", "vocoder_models/ja/kokoro/hifigan_v1")
# ※ vocoder_name은 지원하지 않으니 삭제!

try:
    # vocoder_name 없이 model_name만 사용 (자동으로 vocoder 매핑)
    tts_model = TTS(
        model_name=TTS_MODEL_NAME,
        progress_bar=False,
        gpu=False
    )
except Exception as e:
    raise RuntimeError(f"TTS 모델 로드 실패: {e}")

def synthesize_and_save(text: str, filename: str = "output.wav") -> io.BytesIO:
    """
    text: 합성할 일본어 텍스트
    filename: 임시로 저장할 파일명 (필요시 로컬 저장도 가능)
    반환: WAV 데이터를 담은 BytesIO
    """
    try:
        wav_audio = tts_model.tts(text, speaker=None)  # language 인자 제거
        print("합성된 wav_audio 타입:", type(wav_audio))
        print("합성된 wav_audio 길이:", len(wav_audio))
        sample_rate = tts_model.synthesizer.output_sample_rate

        buffer = io.BytesIO()
        sf.write(buffer, wav_audio, sample_rate, format="WAV")
        print("sf.write 후 버퍼 크기:", buffer.getbuffer().nbytes)
        buffer.seek(0)
        return buffer

    except Exception as ex:
        raise RuntimeError(f"TTS 합성 중 오류: {ex}")

