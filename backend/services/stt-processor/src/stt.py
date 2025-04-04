import os
import logging
from faster_whisper import WhisperModel
from dotenv import load_dotenv

# .env 파일 로드 (선택 사항)
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- 모델 설정 ---
# Dockerfile 또는 docker-compose에서 설정한 환경 변수 사용
MODEL_DIR = os.getenv("MODEL_DIR", "/app/models") # 모델 파일이 저장된 디렉토리
MODEL_SIZE = os.getenv("MODEL_SIZE", "base")      # 사용할 모델 크기 (Dockerfile ARG와 일치)
DEVICE = os.getenv("DEVICE", "cpu")                # "cpu" 또는 "cuda"
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8") # 모델 계산 타입 (성능/정확도 트레이드오프)

# --- 모델 로드 ---
# 서비스 시작 시 모델을 미리 로드하여 요청 처리 속도 향상
stt_model = None
try:
    # 모델 경로 확인 (Dockerfile에서 다운로드한 경로)
    # 모델 이름 형식은 faster-whisper 버전에 따라 다를 수 있으니 확인 필요
    model_load_path = os.path.join(MODEL_DIR, f"faster-whisper-{MODEL_SIZE}")

    if not os.path.exists(model_load_path) and not os.path.isdir(model_load_path):
         # Dockerfile에서 모델을 다운로드하지 않았거나 경로가 잘못된 경우, 여기서 다운로드 시도
         from faster_whisper import download_model
         logger.warning(f"Model not found at {model_load_path}. Attempting to download...")
         model_load_path = download_model(MODEL_SIZE, output_dir=MODEL_DIR)
         logger.info(f"Model downloaded to: {model_load_path}")


    logger.info(f"Loading faster-whisper model '{MODEL_SIZE}' from '{model_load_path}'...")
    logger.info(f"Using device: {DEVICE}, compute_type: {COMPUTE_TYPE}")

    stt_model = WhisperModel(model_load_path, device=DEVICE, compute_type=COMPUTE_TYPE)
    logger.info("Faster-whisper model loaded successfully.")

except Exception as e:
    logger.error(f"Error loading STT model: {e}", exc_info=True)
    # 모델 로드 실패 시 서비스가 정상 작동하지 않으므로, 적절한 처리 필요


# --- STT 함수 ---
def transcribe_audio_file(wav_file_path: str, language: str = "ja") -> str:
    """
    주어진 WAV 파일 경로를 받아 텍스트로 변환합니다.

    Args:
        wav_file_path (str): STT를 수행할 WAV 파일의 컨테이너 내부 경로.
        language (str): 인식할 언어 코드 (기본값: 'ja' - 일본어).

    Returns:
        str: 변환된 텍스트.

    Raises:
        RuntimeError: 모델이 로드되지 않았을 경우.
        FileNotFoundError: WAV 파일이 존재하지 않을 경우.
        Exception: STT 처리 중 오류 발생 시.
    """
    if not stt_model:
        raise RuntimeError("STT model is not loaded. Check logs for errors.")
    if not os.path.exists(wav_file_path):
        raise FileNotFoundError(f"Audio file not found at: {wav_file_path}")

    try:
        logger.info(f"Starting transcription for: {wav_file_path} (Language: {language})")
        # faster-whisper 실행 (옵션 조정 가능)
        segments, info = stt_model.transcribe(
            wav_file_path,
            language=language,
            beam_size=5,         # 탐색 후보 수 (높을수록 정확도 향상 가능성, 속도 저하)
            vad_filter=True,     # 음성 활동 감지 필터 사용 (잡음 제거 효과)
            vad_parameters=dict(min_silence_duration_ms=700) # VAD 파라미터 예시
        )

        # 감지된 언어 정보 로깅
        logger.info(f"Detected language: {info.language} (Probability: {info.language_probability:.2f})")
        logger.info(f"Transcription duration: {info.duration:.2f} seconds")

        # 모든 세그먼트의 텍스트를 합쳐서 반환
        full_text = "".join(segment.text for segment in segments)
        logger.info(f"Transcription successful for: {wav_file_path}")
        return full_text

    except Exception as e:
        logger.error(f"Error during transcription for {wav_file_path}: {e}", exc_info=True)
        raise # 오류를 다시 발생시켜 API 레벨에서 처리

# (선택 사항) 타임스탬프 정보 포함 버전
def transcribe_audio_file_with_timestamps(wav_file_path: str, language: str = "ja") -> list:
    if not stt_model:
        raise RuntimeError("STT model is not loaded.")
    if not os.path.exists(wav_file_path):
        raise FileNotFoundError(f"Audio file not found at: {wav_file_path}")

    try:
        logger.info(f"Starting transcription with timestamps for: {wav_file_path} (Language: {language})")
        segments, info = stt_model.transcribe(
            wav_file_path,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=700)
        )
        logger.info(f"Detected language: {info.language} (Probability: {info.language_probability:.2f})")

        results = [
            {"start": segment.start, "end": segment.end, "text": segment.text}
            for segment in segments
        ]
        logger.info(f"Transcription with timestamps successful for: {wav_file_path}")
        return results
    except Exception as e:
        logger.error(f"Error during transcription with timestamps for {wav_file_path}: {e}", exc_info=True)
        raise