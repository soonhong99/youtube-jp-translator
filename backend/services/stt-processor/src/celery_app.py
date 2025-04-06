import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv() # .env 파일에서 환경 변수 로드 (선택 사항)

# Docker Compose에서 설정할 Redis URL 사용
REDIS_HOST = os.getenv("REDIS_HOST", "redis") # docker-compose 서비스 이름
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
CELERY_BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
CELERY_RESULT_BACKEND = f"redis://{REDIS_HOST}:{REDIS_PORT}/1" # 결과 저장은 다른 DB 사용 권장 (0번과 분리)

# Celery 앱 인스턴스 생성
celery_app = Celery(
    "stt_tasks", # 앱 이름
    broker=CELERY_BROKER_URL, # 메시지 브로커 URL
    backend=CELERY_RESULT_BACKEND, # 결과 백엔드 URL (상태/결과 추적용)
    include=["src.tasks"] # 작업 함수가 정의된 모듈 목록
)

# Celery 설정 (선택 사항)
celery_app.conf.update(
    task_serializer="json",       # 작업 직렬화 방식
    accept_content=["json"],      # 허용할 콘텐츠 타입
    result_serializer="json",     # 결과 직렬화 방식
    timezone="Asia/Seoul",        # 시간대 설정
    enable_utc=True,
    # 작업이 길어질 경우 visibility_timeout 조정 고려
    # broker_transport_options={'visibility_timeout': 7200}, # 예: 2시간
    # worker_prefetch_multiplier=1 # 긴 작업의 경우 prefetch 비활성화 고려
)

# (선택 사항) 특정 작업을 특정 큐로 라우팅
# celery_app.conf.task_routes = {
#     'src.tasks.process_stt_chunk': {'queue': 'gpu_tasks'}, # GPU 작업용 큐 분리 등
# }

if __name__ == "__main__":
    # 개발 환경에서 직접 워커 실행 시 사용 가능
    celery_app.start()