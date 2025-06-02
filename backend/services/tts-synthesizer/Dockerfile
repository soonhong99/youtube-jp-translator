FROM python:3.10-slim

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y \
    espeak \
    ffmpeg \
    && apt-get clean

WORKDIR /app

# .env와 requirements 복사

COPY requirements.txt .

# 파이썬 패키지 설치
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# 애플리케이션 코드 복사
COPY src/ ./src

# 기본 환경 변수 (컨테이너 내)
ENV AUDIO_DIR=/tmp/tts-audio
ENV CLEANUP_THRESHOLD_SECONDS=3600
ENV PORT=8002

# 서버 실행 (shell form으로 ENV PORT 사용)
CMD uvicorn src.main:app --host 0.0.0.0 --port $PORT
