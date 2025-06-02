FROM python:3.10-slim

WORKDIR /app

# 1) requirements.txt 복사 후 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) 코드 파일 복사 (src 폴더, config 폴더)
COPY ./src ./src
COPY ./config ./config

# 3) uvicorn으로 FastAPI 앱 실행 (컨테이너 내부 8000 포트)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
