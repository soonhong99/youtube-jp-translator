import os

KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092') # docker-compose 서비스 이름 사용
STT_REQUEST_TOPIC = 'stt_requests' # STT 요청 토픽
STT_RESULT_TOPIC = 'stt_results'   # STT 결과/진행 토픽