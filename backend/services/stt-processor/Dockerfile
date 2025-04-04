# 1. Base Image 선택 (Python 버전은 프로젝트에 맞게 조정)
FROM python:3.9-slim
# GPU 사용 시: FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04 와 같은 이미지 사용 고려

WORKDIR /app

# 2. 시스템 의존성 설치 (필요 시)
# 예: 오디오 처리를 위한 ffmpeg (youtube-extractor에 이미 있다면 생략 가능)
# RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
#     apt-get clean && rm -rf /var/lib/apt/lists/*

# 3. Python 라이브러리 설치
COPY requirements.txt .
# GPU 사용 및 특정 PyTorch 버전 설치 시 명령어 수정 필요
RUN pip install --no-cache-dir -r requirements.txt

# 4. Faster-Whisper 모델 다운로드 (옵션 1: 빌드 시 포함)
# 환경 변수 또는 인자를 통해 모델 크기 지정 가능
ARG MODEL_SIZE=base # 기본 모델 크기 (예: base, small, medium, large-v2)
ARG MODEL_DIR=/app/models
RUN mkdir -p ${MODEL_DIR}
# 모델 다운로드 스크립트 실행 (필요 시 download_model 함수 사용)
RUN python -c "from faster_whisper import download_model; download_model('${MODEL_SIZE}', output_dir='${MODEL_DIR}')"
# 참고: 모델 파일 크기가 크면 이미지 빌드 시간이 길어지고 이미지 크기가 커집니다.

# 5. 소스 코드 복사
COPY ./src /app/src

# 6. 환경 변수 설정 (모델 경로 등)
ENV MODEL_DIR=${MODEL_DIR}
ENV MODEL_SIZE=${MODEL_SIZE}
# ENV DEVICE=cpu # 기본값 CPU. GPU 사용 시 "cuda"
# ENV COMPUTE_TYPE=int8 # 계산 타입 (int8, float16 등)

# 7. 포트 노출 (FastAPI 기본 포트와 다르게 설정)
EXPOSE 8001

# 8. 애플리케이션 실행 명령어
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]