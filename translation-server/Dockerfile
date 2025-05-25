# # translation-server/Dockerfile

# # Seldon Core Python Wrapper용 베이스 이미지 사용 (버전 확인)
# # seldonio/seldon-core-s2i-python39-ubi8:1.17.0 없음
# FROM seldonio/seldon-core-s2i-python38-ubi8:1.17.0

# # 작업 디렉토리 설정
# ARG APP_ROOT=/app
# WORKDIR ${APP_ROOT}

# # 의존성 파일 복사 및 설치
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# # 추론 코드(Python 클래스) 복사
# COPY TranslatorModel.py .

# # 로컬에 다운로드한 모델 아티팩트들을 이미지 내부 /mnt/models 로 복사
# # (Dockerfile 기준 상대 경로 ./models/...)
# COPY ./models/aihub-ja-ko-translator/ /app/model_files/

# # Seldon Core Wrapper 실행에 필요한 환경 변수 설정
# ENV MODEL_NAME TranslatorModel    
# ENV SERVICE_TYPE MODEL            # 서빙 타입 (MODEL, ROUTER 등)
# ENV MODEL_DIR /app/model_files
# # ENV SELDON_LOG_LEVEL INFO         # 로그 레벨 설정 (선택적)

# # Seldon Core 마이크로서비스 실행 (베이스 이미지에 포함된 스크립트 사용)
# CMD ["seldon-core-microservice", "TranslatorModel", "--service-type", "MODEL", "--persistence", "0", "--access-log"]

# Seldon Core Python Wrapper용 베이스 이미지 사용 (버전 확인)
FROM seldonio/seldon-core-s2i-python38-ubi8:1.17.0

# 작업 디렉토리 설정
ARG APP_ROOT=/app
WORKDIR ${APP_ROOT}

# 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 추론 코드(Python 클래스) 복사
COPY TranslatorModel.py .

# 캐시 디렉토리 생성 및 권한 설정
RUN mkdir -p /tmp/transformers_cache && chmod 777 /tmp/transformers_cache

# 로컬에 다운로드한 모델 아티팩트들을 이미지 내부로 복사
COPY ./models/aihub-ja-ko-translator/ /app/model_files/

# Seldon Core Wrapper 실행에 필요한 환경 변수 설정
ENV MODEL_NAME TranslatorModel    
ENV SERVICE_TYPE MODEL            
ENV MODEL_DIR /app/model_files
ENV TRANSFORMERS_CACHE /tmp/transformers_cache

# Seldon Core 마이크로서비스 실행
CMD ["seldon-core-microservice", "TranslatorModel", "--service-type", "MODEL", "--persistence", "0", "--access-log"]