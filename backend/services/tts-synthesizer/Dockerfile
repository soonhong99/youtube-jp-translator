# FROM python:3.10-slim

# WORKDIR /app

# # 1) 시스템 의존성 설치 (Debian slim에서 soundfile 혹은 espeak 등 필요 시 추가)
# RUN apt-get update && apt-get install -y \
#     libsndfile1   \
#     && apt-get clean

# # 2) requirements.txt 복사 및 pip 설치
# COPY requirements.txt .
# RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# # 3) 소스 코드 복사
# COPY ./src    ./src
# COPY ./config ./config

# # .env를 컨테이너 루트(/app)로 복사

# COPY ./.env   .env

# # 4) FastAPI 실행 (컨테이너 내부 포트 8000)
# CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]


# backend/services/tts-synthesizer/Dockerfile

FROM python:3.10-slim

# 필수 패키지 (libsndfile 등) 설치 (soundfile, TTS가 내부적으로 필요)
RUN apt-get update && apt-get install -y \
    libsndfile1 \
    && apt-get clean

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY src/ ./src

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
