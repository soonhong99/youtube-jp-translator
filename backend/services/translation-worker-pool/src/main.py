"""
Translation Worker Pool Service
멀티 모델 번역 워커 풀 관리 및 지능형 로드 밸런싱
"""

import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional, Any
from enum import Enum

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from kafka import KafkaProducer, KafkaConsumer
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

# 모델 클라이언트 import
import google.generativeai as genai
import anthropic
import openai

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from .config import TranslationWorkerPoolConfig as TWConfig
from .worker_pool_manager import TaskPriority
 
# Kafka producer (for emitting translation_results)
kafka_producer = None

# Prometheus 메트릭
translation_requests_total = Counter('translation_requests_total', 'Total translation requests', ['model', 'status'])
translation_latency = Histogram('translation_latency_seconds', 'Translation latency', ['model'])
active_workers = Gauge('active_workers_total', 'Number of active workers', ['model'])
api_costs = Counter('api_costs_total', 'Total API costs', ['model'])

class ModelType(Enum):
    GEMINI_FLASH = "gemini-1.5-flash"
    GEMINI_PRO = "gemini-2.0-flash"
    CLAUDE_HAIKU = "claude-3-haiku"
    OPENAI_MINI = "gpt-4o-mini"

class TranslationRequest(BaseModel):
    task_id: str
    text_batch: List[str]
    priority: int = 1
    max_latency: int = 30
    quality_requirement: float = 0.7
    context: Optional[Dict] = None

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state_store = {}

    def is_open(self, model_name: str) -> bool:
        """Circuit Breaker 열림 상태 체크"""
        state = self.state_store.get(model_name, {
            "state": "closed",
            "failure_count": 0,
            "last_failure": 0
        })

        if state["state"] == "open":
            if time.time() - state["last_failure"] > self.recovery_timeout:
                state["state"] = "half-open"
                self.state_store[model_name] = state
                return False
            return True

        return False

    def record_failure(self, model_name: str):
        """실패 기록"""
        state = self.state_store.get(model_name, {
            "state": "closed",
            "failure_count": 0,
            "last_failure": 0
        })

        state["failure_count"] += 1
        state["last_failure"] = time.time()

        if state["failure_count"] >= self.failure_threshold:
            state["state"] = "open"
            logger.warning(f"🔴 Circuit breaker opened for {model_name}")

        self.state_store[model_name] = state

    def record_success(self, model_name: str):
        """성공 기록"""
        state = self.state_store.get(model_name, {
            "state": "closed",
            "failure_count": 0,
            "last_failure": 0
        })

        state["failure_count"] = 0
        state["state"] = "closed"
        self.state_store[model_name] = state

class BaseTranslationWorker:
    def __init__(self, model_name: str, max_requests_per_minute: int = 60):
        self.model_name = model_name
        self.max_requests_per_minute = max_requests_per_minute
        self.request_times = []
        self.success_rate = 1.0
        self.avg_response_time = 2.0
        self.current_load = 0

    async def get_current_load(self) -> float:
        """현재 부하율 계산"""
        current_time = time.time()
        # 지난 1분간의 요청 수
        recent_requests = [
            req_time for req_time in self.request_times
            if current_time - req_time < 60
        ]

        self.current_load = len(recent_requests) / self.max_requests_per_minute
        return self.current_load

    def record_request(self):
        """요청 기록"""
        self.request_times.append(time.time())
        # 오래된 기록 정리 (2분 이상)
        cutoff_time = time.time() - 120
        self.request_times = [t for t in self.request_times if t > cutoff_time]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def translate_batch(self, text_batch: List[str], context: Dict = None) -> List[str]:
        """배치 번역 (하위 클래스에서 구현)"""
        raise NotImplementedError

class GeminiWorker(BaseTranslationWorker):
    def __init__(self, model_name: str, max_requests_per_minute: int = 60):
        super().__init__(model_name, max_requests_per_minute)

        # Gemini 클라이언트 초기화
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")

        genai.configure(api_key=api_key)
        self.client = genai.GenerativeModel(model_name)
        logger.info(f"✅ Gemini worker initialized: {model_name}")

    async def translate_batch(self, text_batch: List[str], context: Dict = None) -> List[str]:
        """Gemini 배치 번역"""
        self.record_request()
        start_time = time.time()

        try:
            # 배치 최적화
            separator = "[TRANSLATE_SEP]"
            combined_text = f"\n{separator}\n".join(text_batch)

            prompt = f"""다음은 {len(text_batch)}개의 일본어 문장들입니다. 각 문장을 자연스러운 한국어로 번역하되, 원본의 뉘앙스와 문체를 유지해주세요.
각 번역된 문장 뒤에는 반드시 "{separator}"를 붙여주세요.

일본어 원문:
{combined_text}

한국어 번역:"""

            # 비동기 요청
            response = await asyncio.to_thread(
                self.client.generate_content,
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=2048
                )
            )

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

                # 성능 메트릭 기록
                processing_time = time.time() - start_time
                self.avg_response_time = (self.avg_response_time * 0.9) + (processing_time * 0.1)
                translation_latency.labels(model=self.model_name).observe(processing_time)

                return cleaned_translations[:len(text_batch)]

            return ["[번역 실패]"] * len(text_batch)

        except Exception as e:
            logger.error(f"❌ Gemini translation failed: {e}")
            translation_requests_total.labels(model=self.model_name, status='failed').inc()
            raise

class ClaudeWorker(BaseTranslationWorker):
    def __init__(self, model_name: str, max_requests_per_minute: int = 40):
        super().__init__(model_name, max_requests_per_minute)

        # Claude 클라이언트 초기화
        api_key = os.getenv('CLAUDE_API_KEY')
        if not api_key:
            logger.warning("Claude API key not provided, worker will be disabled")
            return

        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        logger.info(f"✅ Claude worker initialized: {model_name}")

    async def translate_batch(self, text_batch: List[str], context: Dict = None) -> List[str]:
        """Claude 배치 번역"""
        self.record_request()
        start_time = time.time()

        try:
            # 배치 번역 프롬프트
            text_list = "\n".join([f"{i+1}. {text}" for i, text in enumerate(text_batch)])

            prompt = f"""다음 일본어 문장들을 자연스러운 한국어로 번역해주세요. 각 문장의 번호를 유지하고 원본의 뉘앙스를 보존해주세요.

{text_list}

번역 결과 (번호와 함께):"""

            message = await self.client.messages.create(
                model=self.model_name,
                max_tokens=2048,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text

            # 번호별로 분리
            translations = []
            lines = response_text.strip().split('\n')

            for line in lines:
                if line.strip() and '. ' in line:
                    translation = line.split('. ', 1)[1].strip()
                    translations.append(translation)

            # 부족한 번역 채우기
            while len(translations) < len(text_batch):
                translations.append("[번역 누락]")

            # 성능 메트릭 기록
            processing_time = time.time() - start_time
            self.avg_response_time = (self.avg_response_time * 0.9) + (processing_time * 0.1)
            translation_latency.labels(model=self.model_name).observe(processing_time)

            return translations[:len(text_batch)]

        except Exception as e:
            logger.error(f"❌ Claude translation failed: {e}")
            translation_requests_total.labels(model=self.model_name, status='failed').inc()
            raise

class LoadBalancer:
    def __init__(self, workers: Dict[str, BaseTranslationWorker]):
        self.workers = workers
        self.performance_history = {}

    async def select_optimal_worker(self, text_batch: List[str], context: Dict = None) -> BaseTranslationWorker:
        """최적 워커 선택"""
        batch_complexity = self._analyze_batch_complexity(text_batch)

        worker_scores = {}
        for worker_name, worker in self.workers.items():
            if not hasattr(worker, 'client'):  # API 키가 없는 워커 제외
                continue

            # 성능 점수 계산
            performance_score = await self._calculate_performance_score(worker, batch_complexity)

            # 비용 효율성 계산
            cost_score = self._calculate_cost_efficiency(worker, len(text_batch))

            # 현재 부하 상태
            load_score = await self._calculate_load_score(worker)

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

        if not worker_scores:
            raise HTTPException(status_code=503, detail="No available workers")

        # 최고 점수 워커 반환
        best_worker_info = max(worker_scores.values(), key=lambda x: x["score"])
        logger.info(f"🎯 Selected worker: {best_worker_info['worker'].model_name} (score: {best_worker_info['score']:.3f})")

        return best_worker_info["worker"]

    def _analyze_batch_complexity(self, text_batch: List[str]) -> float:
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

    async def _calculate_performance_score(self, worker: BaseTranslationWorker, complexity: float) -> float:
        """성능 점수 계산"""
        # 응답 시간 기반 점수 (낮을수록 좋음)
        time_score = max(0, 1.0 - (worker.avg_response_time / 10.0))

        # 성공률 기반 점수
        success_score = worker.success_rate

        # 복잡도에 따른 가중치
        if complexity > 0.7:  # 복잡한 텍스트
            return (success_score * 0.7) + (time_score * 0.3)
        else:  # 간단한 텍스트
            return (time_score * 0.7) + (success_score * 0.3)

    def _calculate_cost_efficiency(self, worker: BaseTranslationWorker, batch_size: int) -> float:
        """비용 효율성 계산"""
        # 모델별 대략적인 비용 (토큰당)
        cost_per_token = {
            "gemini-1.5-flash": 0.000075,
            "gemini-2.0-flash": 0.0003,
            "claude-3-haiku": 0.00025,
            "gpt-4o-mini": 0.00015
        }

        base_cost = cost_per_token.get(worker.model_name, 0.0002)
        estimated_tokens = batch_size * 50  # 평균 50토큰 추정
        total_cost = base_cost * estimated_tokens

        # 비용이 낮을수록 점수가 높음
        return max(0, 1.0 - (total_cost / 0.1))  # 0.1달러를 기준점으로

    async def _calculate_load_score(self, worker: BaseTranslationWorker) -> float:
        """부하 점수 계산"""
        current_load = await worker.get_current_load()
        return max(0, 1.0 - current_load)

class TranslationWorkerPool:
    def __init__(self):
        self.workers = {}
        self.load_balancer = None
        self.circuit_breaker = CircuitBreaker()
        self.redis_client = None

    async def initialize(self):
        """워커 풀 초기화"""
        try:
            # Redis 연결
            redis_host = os.getenv('REDIS_HOST', 'localhost')
            redis_port = int(os.getenv('REDIS_PORT', '6379'))
            redis_db = int(os.getenv('REDIS_DB_WORKERS', '6'))

            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                decode_responses=True
            )

            await self.redis_client.ping()
            logger.info("✅ Redis connected successfully")

            # 워커 생성
            await self._create_workers()

            # 로드 밸런서 초기화
            self.load_balancer = LoadBalancer(self.workers)

            logger.info(f"✅ Worker pool initialized with {len(self.workers)} workers")

        except Exception as e:
            logger.error(f"❌ Worker pool initialization failed: {e}")
            raise

    async def _create_workers(self):
        """워커 생성"""
        try:
            # Gemini Flash 워커
            if os.getenv('GEMINI_API_KEY'):
                self.workers["gemini_flash"] = GeminiWorker("gemini-1.5-flash-latest", 60)
                self.workers["gemini_pro"] = GeminiWorker("gemini-2.0-flash-exp", 30)

            # Claude 워커
            if os.getenv('CLAUDE_API_KEY'):
                self.workers["claude_haiku"] = ClaudeWorker("claude-3-haiku-20240307", 40)

            # OpenAI 워커는 일단 제외 (API 키 설정 시 추가)

        except Exception as e:
            logger.error(f"❌ Worker creation failed: {e}")
            raise

    async def translate_batch(self, request: TranslationRequest) -> Dict[str, Any]:
        """배치 번역 처리"""
        start_time = time.time()

        try:
            # 최적 워커 선택
            selected_worker = await self.load_balancer.select_optimal_worker(
                request.text_batch, request.context
            )

            # Circuit Breaker 체크
            if self.circuit_breaker.is_open(selected_worker.model_name):
                # Fallback 워커 선택
                fallback_worker = await self._select_fallback_worker(selected_worker)
                if fallback_worker:
                    selected_worker = fallback_worker
                else:
                    raise HTTPException(status_code=503, detail="All workers unavailable")

            # 번역 실행
            translations = await asyncio.wait_for(
                selected_worker.translate_batch(request.text_batch, request.context),
                timeout=request.max_latency
            )

            # 성공 메트릭 기록
            processing_time = time.time() - start_time
            translation_requests_total.labels(model=selected_worker.model_name, status='success').inc()
            self.circuit_breaker.record_success(selected_worker.model_name)

            return {
                "task_id": request.task_id,
                "translations": translations,
                "model_used": selected_worker.model_name,
                "processing_time": processing_time,
                "status": "completed"
            }

        except asyncio.TimeoutError:
            translation_requests_total.labels(model=selected_worker.model_name, status='timeout').inc()
            self.circuit_breaker.record_failure(selected_worker.model_name)
            raise HTTPException(status_code=408, detail="Translation timeout")

        except Exception as e:
            logger.error(f"❌ Translation failed for {request.task_id}: {e}")
            translation_requests_total.labels(model=selected_worker.model_name, status='error').inc()
            self.circuit_breaker.record_failure(selected_worker.model_name)
            raise HTTPException(status_code=500, detail=str(e))

    async def _select_fallback_worker(self, failed_worker: BaseTranslationWorker) -> Optional[BaseTranslationWorker]:
        """Fallback 워커 선택"""
        for worker_name, worker in self.workers.items():
            if (worker != failed_worker and
                not self.circuit_breaker.is_open(worker.model_name) and
                hasattr(worker, 'client')):
                return worker
        return None

# FastAPI 앱 초기화
app = FastAPI(title="Translation Worker Pool Service", version="1.0.0")
worker_pool = TranslationWorkerPool()

@app.on_event("startup")
async def startup_event():
    """서비스 시작 시 초기화"""
    await worker_pool.initialize()

    # Prometheus 메트릭 서버 시작
    start_http_server(8000)
    logger.info("📊 Prometheus metrics server started on port 8000")

    # Kafka 프로듀서 초기화 및 컨슈머 시작
    global kafka_producer
    kafka_producer = KafkaProducer(
        bootstrap_servers=TWConfig.KAFKA_BOOTSTRAP_SERVERS.split(','),
        value_serializer=lambda x: json.dumps(x, ensure_ascii=False).encode('utf-8'),
        key_serializer=lambda x: x.encode('utf-8') if x else None
    )
    asyncio.create_task(consume_translation_queue())

async def consume_translation_queue():
    """translation_queue를 소비하여 번역 처리 후 결과를 발행"""
    try:
        consumer = KafkaConsumer(
            TWConfig.KAFKA_TOPIC_TRANSLATION_QUEUE,
            bootstrap_servers=TWConfig.KAFKA_BOOTSTRAP_SERVERS.split(','),
            group_id='translation-worker-pool',
            auto_offset_reset='latest',
            value_deserializer=lambda x: json.loads(x.decode('utf-8'))
        )
        logger.info("🎧 Kafka 컨슈머 시작: translation_queue")

        while True:
            records = await asyncio.to_thread(consumer.poll, timeout_ms=1000)
            if not records:
                continue
            for _tp, messages in records.items():
                for message in messages:
                    try:
                        data = message.value or {}
                        task_id = data.get('task_id')
                        if not task_id:
                            continue
                        text = data.get('text', '')
                        chunk_id = data.get('chunk_id', 'chunk')
                        prio_raw = data.get('priority', 'NORMAL')
                        if isinstance(prio_raw, int):
                            try:
                                priority_enum = TaskPriority(prio_raw)
                            except Exception:
                                priority_enum = TaskPriority.NORMAL
                        else:
                            try:
                                priority_enum = TaskPriority[str(prio_raw).upper()]
                            except Exception:
                                priority_enum = TaskPriority.NORMAL
                        max_latency = float(data.get('max_latency', 30.0))
                        context = data.get('context')

                        req = TranslationRequest(
                            task_id=task_id,
                            text_batch=[text],
                            priority=1 if priority_enum == TaskPriority.CRITICAL else 2 if priority_enum == TaskPriority.HIGH else 3 if priority_enum == TaskPriority.NORMAL else 4,
                            max_latency=int(max_latency),
                            quality_requirement=0.7,
                            context=context
                        )

                        result = await worker_pool.translate_batch(req)
                        translations = result.get('translations') or []
                        model_used = result.get('model_used', 'unknown')
                        processing_time = result.get('processing_time', 0.0)
                        translated_text = translations[0] if translations else "[번역 실패]"

                        out_msg = {
                            'type': 'translation_result',
                            'task_id': task_id,
                            'chunk_id': chunk_id,
                            'original_text': text,
                            'translated_text': translated_text,
                            'worker_used': model_used,
                            'processing_time': processing_time,
                            'timestamp': time.time()
                        }
                        kafka_producer.send(
                            TWConfig.KAFKA_TOPIC_TRANSLATION_RESULTS,
                            key=task_id,
                            value=out_msg
                        )
                        kafka_producer.flush()
                        logger.info(f"📤 번역 결과 전송: {task_id}/{chunk_id}")
                    except Exception as e:
                        logger.error(f"❌ translation_queue 처리 실패: {e}")
    except Exception as e:
        logger.error(f"❌ Kafka 컨슈머 오류(translation_queue): {e}")

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    try:
        await worker_pool.redis_client.ping()

        return {
            "status": "healthy",
            "available_workers": len(worker_pool.workers),
            "worker_status": {
                name: {
                    "model": worker.model_name,
                    "current_load": await worker.get_current_load(),
                    "avg_response_time": worker.avg_response_time,
                    "circuit_breaker": worker_pool.circuit_breaker.state_store.get(worker.model_name, {}).get("state", "closed")
                }
                for name, worker in worker_pool.workers.items()
                if hasattr(worker, 'client')
            },
            "timestamp": time.time()
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@app.post("/translate")
async def translate_batch(request: TranslationRequest):
    """배치 번역 처리"""
    return await worker_pool.translate_batch(request)

@app.get("/workers/status")
async def get_workers_status():
    """워커 상태 조회"""
    status = {}
    for name, worker in worker_pool.workers.items():
        if hasattr(worker, 'client'):
            status[name] = {
                "model": worker.model_name,
                "current_load": await worker.get_current_load(),
                "avg_response_time": worker.avg_response_time,
                "success_rate": worker.success_rate,
                "circuit_breaker": worker_pool.circuit_breaker.state_store.get(worker.model_name, {}).get("state", "closed")
            }
    return status

@app.get("/metrics")
async def get_metrics():
    """메트릭 조회"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response

    return Response(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
