# 🎯 단계별 마이그레이션 전략: 스트리밍 번역 최적화

## 📋 **전체 마이그레이션 로드맵**

### **Phase 1: 기반 인프라 구축 (1-2주)**
- **목표**: 병렬 처리 인프라 및 모니터링 시스템 구축
- **위험도**: 낮음 (기존 시스템과 병렬 운영)

### **Phase 2: 스트리밍 STT 구현 (2-3주)**
- **목표**: 청크 기반 실시간 STT 처리
- **위험도**: 중간 (STT 파이프라인 변경)

### **Phase 3: 번역 워커 풀 도입 (2-3주)**
- **목표**: 멀티 모델 병렬 번역 시스템
- **위험도**: 중간 (API 처리 방식 변경)

### **Phase 4: 지능형 버퍼링 통합 (1-2주)**
- **목표**: 문맥 기반 실시간 처리
- **위험도**: 높음 (전체 워크플로우 변경)

### **Phase 5: 최종 최적화 및 안정화 (1-2주)**
- **목표**: 성능 튜닝 및 모니터링 완성
- **위험도**: 낮음 (기능 완성 단계)

---

## 🔧 **Phase 1: 기반 인프라 구축**

### **1.1 Docker Compose 확장**

```yaml
# docker-compose.streaming.yml (기존 파일에 추가)
version: '3.8'

services:
  # 새로운 스트리밍 서비스들
  streaming-coordinator:
    build: ./services/streaming-coordinator
    container_name: streaming-coordinator
    environment:
      - REDIS_HOST=redis
      - KAFKA_BOOTSTRAP_SERVERS=kafka:9092
      - LOG_LEVEL=INFO
    depends_on:
      - redis
      - kafka
    networks:
      - backend-network

  translation-worker-pool:
    build: ./services/translation-worker-pool
    container_name: translation-worker-pool
    environment:
      - REDIS_HOST=redis
      - KAFKA_BOOTSTRAP_SERVERS=kafka:9092
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - CLAUDE_API_KEY=${CLAUDE_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - WORKER_POOL_SIZE=5
    depends_on:
      - redis
      - kafka
    networks:
      - backend-network
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G

  performance-monitor:
    build: ./services/performance-monitor
    container_name: performance-monitor
    environment:
      - REDIS_HOST=redis
      - PROMETHEUS_ENDPOINT=http://prometheus:9090
      - GRAFANA_ENDPOINT=http://grafana:3000
    depends_on:
      - redis
    networks:
      - backend-network

  # 모니터링 도구들
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    ports:
      - "127.0.0.1:9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    networks:
      - backend-network
    profiles:
      - monitoring

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "127.0.0.1:3001:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards
    networks:
      - backend-network
    profiles:
      - monitoring

volumes:
  prometheus_data:
  grafana_data:
```

### **1.2 새로운 Kafka 토픽 생성**

```bash
# scripts/setup-streaming-topics.sh
#!/bin/bash

echo "Creating streaming-specific Kafka topics..."

# 스트리밍 STT 토픽
kafka-topics --create --if-not-exists --topic stt_chunks --bootstrap-server kafka:9092 --partitions 5 --replication-factor 1

# 번역 작업 큐
kafka-topics --create --if-not-exists --topic translation_queue --bootstrap-server kafka:9092 --partitions 8 --replication-factor 1

# 실시간 결과 스트림
kafka-topics --create --if-not-exists --topic realtime_results --bootstrap-server kafka:9092 --partitions 3 --replication-factor 1

# 모니터링 메트릭
kafka-topics --create --if-not-exists --topic performance_metrics --bootstrap-server kafka:9092 --partitions 2 --replication-factor 1

echo "Streaming topics created successfully!"
```

### **1.3 성능 모니터링 시스템**

```python
# services/performance-monitor/src/metrics_collector.py
import asyncio
import time
from prometheus_client import Counter, Histogram, Gauge, start_http_server
import redis
from kafka import KafkaConsumer
import json

class PerformanceMetricsCollector:
    def __init__(self):
        # Prometheus 메트릭 정의
        self.stt_processing_time = Histogram('stt_processing_seconds', 'STT processing time', ['chunk_size'])
        self.translation_latency = Histogram('translation_latency_seconds', 'Translation latency', ['model', 'batch_size'])
        self.api_requests_total = Counter('api_requests_total', 'Total API requests', ['model', 'status'])
        self.active_tasks = Gauge('active_tasks_total', 'Number of active tasks')
        self.system_load = Gauge('system_load_percent', 'System load percentage')

        # Redis 클라이언트
        self.redis_client = redis.Redis(host='redis', port=6379, db=6)

        # Kafka 컨슈머
        self.consumer = KafkaConsumer(
            'performance_metrics',
            bootstrap_servers=['kafka:9092'],
            value_deserializer=lambda v: json.loads(v.decode('utf-8'))
        )

    async def start_monitoring(self):
        """모니터링 시작"""
        # Prometheus HTTP 서버 시작
        start_http_server(8000)

        # 메트릭 수집 시작
        await asyncio.gather(
            self.collect_kafka_metrics(),
            self.collect_system_metrics(),
            self.collect_redis_metrics()
        )

    async def collect_kafka_metrics(self):
        """Kafka에서 성능 메트릭 수집"""
        for message in self.consumer:
            metric_data = message.value
            metric_type = metric_data.get('type')

            if metric_type == 'stt_processing':
                self.stt_processing_time.labels(
                    chunk_size=metric_data.get('chunk_size', 'unknown')
                ).observe(metric_data.get('processing_time', 0))

            elif metric_type == 'translation':
                self.translation_latency.labels(
                    model=metric_data.get('model', 'unknown'),
                    batch_size=metric_data.get('batch_size', 'unknown')
                ).observe(metric_data.get('latency', 0))

                self.api_requests_total.labels(
                    model=metric_data.get('model', 'unknown'),
                    status=metric_data.get('status', 'unknown')
                ).inc()

    async def collect_system_metrics(self):
        """시스템 메트릭 수집"""
        while True:
            # 활성 작업 수
            active_tasks_count = await self.get_active_tasks_count()
            self.active_tasks.set(active_tasks_count)

            # 시스템 부하
            load_percent = await self.get_system_load_percent()
            self.system_load.set(load_percent)

            await asyncio.sleep(10)  # 10초마다 수집
```

---

## 🔄 **Phase 2: 스트리밍 STT 구현**

### **2.1 새로운 스트리밍 STT 서비스 생성**

```bash
# 새로운 서비스 디렉토리 구조
backend/services/streaming-stt-processor/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 애플리케이션
│   ├── streaming_worker.py        # 스트리밍 워커
│   ├── audio_chunker.py          # 오디오 청킹 로직
│   ├── sentence_detector.py      # 문장 경계 감지
│   ├── whisper_pool.py           # Whisper 모델 풀
│   └── kafka_producer.py         # Kafka 프로듀서
└── config/
    └── streaming_config.py
```

### **2.2 핵심 구현 파일들**

```python
# services/streaming-stt-processor/src/streaming_worker.py
import asyncio
from typing import List, Dict, Any
from faster_whisper import WhisperModel
import time
import numpy as np
from pydub import AudioSegment

class StreamingSTTWorker:
    def __init__(self):
        self.chunk_duration = 5  # 5초 청크
        self.overlap_duration = 1  # 1초 오버랩
        self.whisper_pool = WhisperModelPool(pool_size=3)
        self.sentence_detector = JapaneseSentenceDetector()
        self.kafka_producer = StreamingKafkaProducer()

    async def process_audio_stream(self, audio_file_path: str, task_id: str):
        """오디오 파일을 스트리밍 방식으로 처리"""
        # 1. 오디오 파일 로드
        audio = AudioSegment.from_wav(audio_file_path)
        total_duration = len(audio) / 1000.0  # 초 단위

        # 2. 청크별 처리
        chunk_tasks = []
        for start_time in range(0, int(total_duration), self.chunk_duration - self.overlap_duration):
            end_time = min(start_time + self.chunk_duration, total_duration)

            # 청크 추출
            start_ms = start_time * 1000
            end_ms = end_time * 1000
            chunk_audio = audio[start_ms:end_ms]

            # 비동기 STT 처리
            task = asyncio.create_task(
                self.process_audio_chunk(chunk_audio, start_time, end_time, task_id)
            )
            chunk_tasks.append(task)

            # 너무 많은 동시 작업 방지
            if len(chunk_tasks) >= 3:
                completed_tasks = await asyncio.gather(*chunk_tasks[:3])
                await self.handle_chunk_results(completed_tasks, task_id)
                chunk_tasks = chunk_tasks[3:]

        # 남은 작업 완료
        if chunk_tasks:
            completed_tasks = await asyncio.gather(*chunk_tasks)
            await self.handle_chunk_results(completed_tasks, task_id)

    async def process_audio_chunk(self, chunk_audio: AudioSegment,
                                 start_time: float, end_time: float, task_id: str):
        """개별 오디오 청크 처리"""
        # 1. 임시 파일로 저장
        temp_path = f"/tmp/{task_id}_chunk_{start_time}_{end_time}.wav"
        chunk_audio.export(temp_path, format="wav")

        try:
            # 2. Whisper 모델로 STT 처리
            model = await self.whisper_pool.acquire()

            segments, info = model.transcribe(
                temp_path,
                language="ja",
                word_timestamps=True,
                vad_filter=True
            )

            # 3. 결과 정리
            chunk_result = {
                "task_id": task_id,
                "chunk_start": start_time,
                "chunk_end": end_time,
                "segments": [],
                "language": info.language,
                "language_probability": info.language_probability
            }

            for segment in segments:
                chunk_result["segments"].append({
                    "start": segment.start + start_time,
                    "end": segment.end + start_time,
                    "text": segment.text,
                    "words": [
                        {
                            "word": word.word,
                            "start": word.start + start_time,
                            "end": word.end + start_time,
                            "probability": word.probability
                        }
                        for word in segment.words
                    ] if segment.words else []
                })

            return chunk_result

        finally:
            # 4. 리소스 정리
            await self.whisper_pool.release(model)
            os.unlink(temp_path)

    async def handle_chunk_results(self, chunk_results: List[Dict], task_id: str):
        """청크 결과 처리 및 문장 경계 감지"""
        for result in chunk_results:
            if not result or not result.get("segments"):
                continue

            # 1. 문장 경계 감지
            sentence_boundaries = await self.sentence_detector.detect_boundaries(
                result["segments"]
            )

            # 2. 완성된 문장이 있으면 번역 큐로 전송
            if sentence_boundaries["complete_sentences"]:
                await self.kafka_producer.send_to_translation_queue(
                    sentence_boundaries["complete_sentences"],
                    task_id
                )

            # 3. 부분 결과도 WebSocket으로 전송 (실시간 피드백)
            await self.kafka_producer.send_partial_result(result, task_id)

class WhisperModelPool:
    def __init__(self, pool_size: int = 3):
        self.pool_size = pool_size
        self.models = []
        self.available_models = asyncio.Queue()
        self._initialized = False

    async def initialize(self):
        """모델 풀 초기화"""
        if self._initialized:
            return

        for i in range(self.pool_size):
            model = WhisperModel("base", device="cpu", compute_type="int8")
            self.models.append(model)
            await self.available_models.put(model)

        self._initialized = True

    async def acquire(self) -> WhisperModel:
        """모델 획득"""
        if not self._initialized:
            await self.initialize()

        return await self.available_models.get()

    async def release(self, model: WhisperModel):
        """모델 반환"""
        await self.available_models.put(model)

class JapaneseSentenceDetector:
    def __init__(self):
        self.sentence_endings = [
            r'[。！？]+',
            r'です[。\s]*',
            r'ます[。\s]*',
            r'だ[。\s]*',
            r'である[。\s]*'
        ]

    async def detect_boundaries(self, segments: List[Dict]) -> Dict[str, Any]:
        """문장 경계 감지"""
        complete_sentences = []
        partial_sentences = []

        current_sentence = ""
        current_words = []

        for segment in segments:
            text = segment.get("text", "").strip()
            words = segment.get("words", [])

            current_sentence += text
            current_words.extend(words)

            # 문장 완성 여부 확인
            if self.is_sentence_complete(current_sentence):
                complete_sentences.append({
                    "text": current_sentence.strip(),
                    "words": current_words,
                    "start": current_words[0]["start"] if current_words else segment["start"],
                    "end": current_words[-1]["end"] if current_words else segment["end"]
                })
                current_sentence = ""
                current_words = []
            else:
                partial_sentences.append({
                    "text": current_sentence.strip(),
                    "words": current_words.copy()
                })

        return {
            "complete_sentences": complete_sentences,
            "partial_sentences": partial_sentences
        }

    def is_sentence_complete(self, text: str) -> bool:
        """문장 완성 여부 판단"""
        import re
        for pattern in self.sentence_endings:
            if re.search(pattern, text):
                return True
        return False
```

### **2.3 기존 시스템과의 통합**

```python
# services/api-gateway/src/streaming_handler.py
class StreamingTranslationHandler:
    def __init__(self):
        self.streaming_stt = StreamingSTTClient()
        self.legacy_stt = LegacySTTClient()
        self.feature_flag = FeatureFlag()

    async def handle_translation_request(self, request: TranscriptionRequest):
        """요청 라우팅 (기존 vs 스트리밍)"""
        # 피처 플래그 기반 라우팅
        if await self.feature_flag.is_streaming_enabled(request.task_id):
            return await self.streaming_stt.process_request(request)
        else:
            return await self.legacy_stt.process_request(request)

class FeatureFlag:
    def __init__(self):
        self.redis_client = redis.Redis(host='redis', port=6379, db=7)

    async def is_streaming_enabled(self, task_id: str) -> bool:
        """스트리밍 모드 활성화 여부"""
        # 점진적 롤아웃: 일부 사용자부터 시작
        rollout_percentage = await self.get_rollout_percentage()

        # 태스크 ID 기반 해시로 일관된 라우팅
        import hashlib
        hash_value = int(hashlib.md5(task_id.encode()).hexdigest(), 16)
        user_percentage = hash_value % 100

        return user_percentage < rollout_percentage

    async def get_rollout_percentage(self) -> int:
        """현재 롤아웃 비율"""
        stored_value = await self.redis_client.get("streaming_rollout_percentage")
        return int(stored_value) if stored_value else 0
```

---

## 🔄 **Phase 3: 번역 워커 풀 도입**

### **3.1 Translation Worker Pool 서비스**

```python
# services/translation-worker-pool/src/worker_pool_manager.py
import asyncio
from typing import Dict, List, Any
import time
from enum import Enum

class ModelType(Enum):
    GEMINI_FLASH = "gemini-1.5-flash"
    GEMINI_PRO = "gemini-2.0-flash"
    CLAUDE_HAIKU = "claude-3-haiku"
    OPENAI_MINI = "gpt-4o-mini"

class TranslationWorkerPool:
    def __init__(self):
        self.workers = {}
        self.load_balancer = IntelligentLoadBalancer()
        self.circuit_breaker = CircuitBreaker()
        self.metrics_reporter = MetricsReporter()

    async def initialize(self):
        """워커 풀 초기화"""
        # 각 모델별 워커 생성
        for model_type in ModelType:
            worker = await self.create_worker(model_type)
            self.workers[model_type.value] = worker

        # 헬스 체크 시작
        asyncio.create_task(self.health_check_loop())

    async def create_worker(self, model_type: ModelType):
        """모델별 워커 생성"""
        if model_type == ModelType.GEMINI_FLASH:
            return GeminiWorker("gemini-1.5-flash-latest", max_requests_per_minute=60)
        elif model_type == ModelType.GEMINI_PRO:
            return GeminiWorker("gemini-2.0-flash-exp", max_requests_per_minute=30)
        elif model_type == ModelType.CLAUDE_HAIKU:
            return ClaudeWorker("claude-3-haiku-20240307", max_requests_per_minute=40)
        elif model_type == ModelType.OPENAI_MINI:
            return OpenAIWorker("gpt-4o-mini", max_requests_per_minute=50)

    async def translate_batch(self, text_batch: List[str], task_context: Dict) -> List[str]:
        """지능형 로드 밸런싱 번역"""
        start_time = time.time()

        try:
            # 1. 최적 워커 선택
            selected_worker = await self.load_balancer.select_optimal_worker(
                text_batch, self.workers, task_context
            )

            # 2. Circuit Breaker 체크
            if self.circuit_breaker.is_open(selected_worker.model_name):
                # Fallback 워커 선택
                selected_worker = await self.load_balancer.select_fallback_worker(
                    text_batch, self.workers, task_context
                )

            # 3. 번역 실행
            result = await selected_worker.translate_with_timeout(
                text_batch,
                timeout=30,
                context=task_context
            )

            # 4. 성공 메트릭 기록
            processing_time = time.time() - start_time
            await self.metrics_reporter.record_success(
                selected_worker.model_name,
                len(text_batch),
                processing_time
            )

            self.circuit_breaker.record_success(selected_worker.model_name)
            return result

        except Exception as e:
            # 5. 실패 처리
            processing_time = time.time() - start_time
            await self.metrics_reporter.record_failure(
                selected_worker.model_name,
                str(e),
                processing_time
            )

            self.circuit_breaker.record_failure(selected_worker.model_name)

            # 6. 재시도 또는 대체 방안
            return await self.handle_translation_failure(text_batch, task_context, e)

class IntelligentLoadBalancer:
    def __init__(self):
        self.performance_history = {}
        self.cost_calculator = CostCalculator()

    async def select_optimal_worker(self, text_batch: List[str],
                                   workers: Dict, task_context: Dict):
        """최적 워커 선택"""
        batch_complexity = await self.analyze_batch_complexity(text_batch)

        worker_scores = {}
        for worker_name, worker in workers.items():
            # 성능 점수 계산
            performance_score = await self.calculate_performance_score(
                worker, batch_complexity, task_context
            )

            # 비용 효율성 계산
            cost_score = await self.cost_calculator.calculate_cost_efficiency(
                worker, len(text_batch), batch_complexity
            )

            # 현재 부하 상태
            load_score = await self.calculate_load_score(worker)

            # 종합 점수
            total_score = (
                performance_score * 0.4 +
                cost_score * 0.3 +
                load_score * 0.3
            )

            worker_scores[worker_name] = {
                "score": total_score,
                "worker": worker,
                "performance": performance_score,
                "cost": cost_score,
                "load": load_score
            }

        # 최고 점수 워커 반환
        best_worker_info = max(worker_scores.values(), key=lambda x: x["score"])
        return best_worker_info["worker"]

    async def analyze_batch_complexity(self, text_batch: List[str]) -> float:
        """배치 복잡도 분석"""
        if not text_batch:
            return 0.0

        total_complexity = 0.0
        for text in text_batch:
            # 문장 길이 기반 복잡도
            length_complexity = min(len(text) / 100.0, 1.0)

            # 특수 문자 및 문체 복잡도
            import re
            special_chars = len(re.findall(r'[^\w\s]', text))
            special_complexity = min(special_chars / 20.0, 0.5)

            # 경어/존댓말 사용 (번역 난이도 증가)
            formal_patterns = ['です', 'ます', 'でした', 'ました']
            formal_complexity = 0.3 if any(pattern in text for pattern in formal_patterns) else 0.0

            text_complexity = length_complexity + special_complexity + formal_complexity
            total_complexity += min(text_complexity, 2.0)

        return total_complexity / len(text_batch)

class BaseTranslationWorker:
    def __init__(self, model_name: str, max_requests_per_minute: int):
        self.model_name = model_name
        self.max_requests_per_minute = max_requests_per_minute
        self.current_load = 0
        self.request_times = []
        self.success_rate = 1.0
        self.avg_response_time = 2.0

    async def translate_with_timeout(self, text_batch: List[str],
                                   timeout: int, context: Dict) -> List[str]:
        """타임아웃이 있는 번역"""
        try:
            return await asyncio.wait_for(
                self.translate_batch(text_batch, context),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"Translation timeout after {timeout}s")

    async def translate_batch(self, text_batch: List[str], context: Dict) -> List[str]:
        """배치 번역 (하위 클래스에서 구현)"""
        raise NotImplementedError

    async def get_current_load(self) -> float:
        """현재 부하율 계산"""
        current_time = time.time()
        # 지난 1분간의 요청 수
        recent_requests = [
            req_time for req_time in self.request_times
            if current_time - req_time < 60
        ]

        return len(recent_requests) / self.max_requests_per_minute

    def record_request(self):
        """요청 기록"""
        self.request_times.append(time.time())
        # 오래된 기록 정리 (2분 이상)
        cutoff_time = time.time() - 120
        self.request_times = [t for t in self.request_times if t > cutoff_time]

class GeminiWorker(BaseTranslationWorker):
    def __init__(self, model_name: str, max_requests_per_minute: int):
        super().__init__(model_name, max_requests_per_minute)
        import google.generativeai as genai
        self.client = genai.GenerativeModel(model_name)

    async def translate_batch(self, text_batch: List[str], context: Dict) -> List[str]:
        """Gemini 배치 번역"""
        self.record_request()

        # 배치 최적화
        separator = "[TRANSLATE_SEP]"
        combined_text = f"\n{separator}\n".join(text_batch)

        prompt = f"""다음은 {len(text_batch)}개의 일본어 문장들입니다. 각 문장을 자연스러운 한국어로 번역하되, 원본의 뉘앙스와 문체를 유지해주세요.
        각 번역된 문장 뒤에는 반드시 "{separator}"를 붙여주세요.

        일본어 원문:
        {combined_text}

        한국어 번역:"""

        response = await self.client.generate_content_async(prompt)

        if response.parts:
            translated_text = response.text.strip()
            translations = translated_text.split(f"{separator}\n")

            # 결과 정리
            cleaned_translations = []
            for translation in translations:
                cleaned = translation.strip().replace(separator, "")
                if cleaned:
                    cleaned_translations.append(cleaned)

            # 입력과 출력 수 맞추기
            while len(cleaned_translations) < len(text_batch):
                cleaned_translations.append("[번역 누락]")

            return cleaned_translations[:len(text_batch)]

        return ["[번역 실패]"] * len(text_batch)
```

---

## 📊 **마이그레이션 실행 계획 요약**

### **단계별 실행 순서**

| 단계 | 기간 | 주요 작업 | 성공 지표 | 위험 완화 방안 |
|------|------|----------|----------|------------|
| **Phase 1** | 1-2주 | 인프라 구축 | 모니터링 대시보드 활성화 | 기존 시스템과 병렬 운영 |
| **Phase 2** | 2-3주 | 스트리밍 STT | 첫 결과 < 10초 | 피처 플래그로 점진적 롤아웃 |
| **Phase 3** | 2-3주 | 번역 워커 풀 | API 비용 30% 절감 | Circuit Breaker로 장애 격리 |
| **Phase 4** | 1-2주 | 지능형 버퍼링 | 전체 처리 시간 < 30초 | A/B 테스트로 성능 검증 |
| **Phase 5** | 1-2주 | 최적화 완료 | 목표 성능 달성 | 자동 롤백 메커니즘 |

### **예상 최종 성능**

| 메트릭 | 현재 | 목표 | 개선율 |
|--------|------|------|--------|
| **첫 번역 결과** | 120초 | 8초 | **93% 단축** |
| **전체 완료 시간** | 120초 | 30초 | **75% 단축** |
| **API 비용** | $0.067 | $0.025 | **60% 절감** |
| **시스템 처리량** | 10 req/min | 100+ req/min | **10배 증가** |

이 마이그레이션 계획을 통해 **점진적이고 안전한 성능 최적화**를 달성할 수 있습니다.