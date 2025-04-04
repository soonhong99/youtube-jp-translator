FROM python:3.9-slim

WORKDIR /app

# FFmpeg 및 기타 필요한 패키지 설치
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 필요한 Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# 애플리케이션 실행
CMD ["python", "-m", "src.main"]