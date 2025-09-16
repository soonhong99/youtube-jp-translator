# 번역 워커 풀 설계

## 멀티 모델 로드 밸런싱

```python
class TranslationWorkerPool:
    def __init__(self):
        self.workers = {
            "fast": GeminiWorker("gemini-1.5-flash", priority="speed"),
            "quality": GeminiWorker("gemini-2.0-flash", priority="quality"),
            "backup": ClaudeWorker("claude-haiku", priority="backup")
        }
        self.circuit_breaker = CircuitBreaker()
        self.load_balancer = LoadBalancer()

    async def translate_batch(self, sentences, task_id):
        """지능형 로드 밸런싱 번역"""
        # 1. 최적 워커 선택
        worker = await self.load_balancer.select_worker(
            sentences, self.workers, self.circuit_breaker.get_status()
        )

        # 2. Circuit Breaker 체크
        if self.circuit_breaker.is_open(worker.name):
            worker = await self.get_fallback_worker(worker)

        # 3. 병렬 번역 실행
        try:
            result = await worker.translate_with_timeout(sentences, timeout=10)
            self.circuit_breaker.record_success(worker.name)
            return result
        except Exception as e:
            self.circuit_breaker.record_failure(worker.name)
            return await self.handle_translation_failure(sentences, worker, e)

class LoadBalancer:
    def __init__(self):
        self.metrics = {
            "avg_response_time": {},
            "success_rate": {},
            "current_load": {}
        }

    async def select_worker(self, sentences, workers, breaker_status):
        """동적 워커 선택"""
        # 문장 복잡도 분석
        complexity = self.analyze_sentence_complexity(sentences)

        # 현재 부하 상황 고려
        current_loads = {name: worker.get_current_load()
                        for name, worker in workers.items()}

        # 할당량 상태 고려
        quota_status = {name: worker.get_quota_remaining()
                       for name, worker in workers.items()}

        # 종합 점수 계산
        scores = {}
        for name, worker in workers.items():
            if breaker_status[name]["state"] == "open":
                continue

            score = self.calculate_worker_score(
                worker, complexity, current_loads[name], quota_status[name]
            )
            scores[name] = score

        # 최고 점수 워커 선택
        best_worker = max(scores.items(), key=lambda x: x[1])
        return workers[best_worker[0]]

    def calculate_worker_score(self, worker, complexity, load, quota):
        """워커 점수 계산 (높을수록 선호)"""
        speed_score = 1.0 / (worker.avg_response_time + 0.1)
        load_score = 1.0 / (load + 0.1)
        quota_score = quota / 100.0
        quality_score = worker.quality_rating

        # 복잡도에 따른 가중치 조정
        if complexity > 0.7:  # 복잡한 문장
            return quality_score * 0.4 + speed_score * 0.2 + load_score * 0.2 + quota_score * 0.2
        else:  # 간단한 문장
            return speed_score * 0.4 + load_score * 0.3 + quota_score * 0.2 + quality_score * 0.1

class CircuitBreaker:
    def __init__(self):
        self.failure_threshold = 5
        self.timeout = 60  # 60초 후 재시도
        self.state_store = {}

    def is_open(self, worker_name):
        """Circuit Breaker 열림 상태 체크"""
        state = self.state_store.get(worker_name, {
            "state": "closed",
            "failure_count": 0,
            "last_failure": 0
        })

        if state["state"] == "open":
            if time.time() - state["last_failure"] > self.timeout:
                state["state"] = "half-open"
                self.state_store[worker_name] = state
                return False
            return True

        return False

    def record_failure(self, worker_name):
        """실패 기록"""
        state = self.state_store.get(worker_name, {
            "state": "closed",
            "failure_count": 0,
            "last_failure": 0
        })

        state["failure_count"] += 1
        state["last_failure"] = time.time()

        if state["failure_count"] >= self.failure_threshold:
            state["state"] = "open"

        self.state_store[worker_name] = state

    def record_success(self, worker_name):
        """성공 기록"""
        state = self.state_store.get(worker_name, {
            "state": "closed",
            "failure_count": 0,
            "last_failure": 0
        })

        state["failure_count"] = 0
        state["state"] = "closed"
        self.state_store[worker_name] = state
```

## 성능 최적화 전략

### 1. 배치 크기 동적 조정
```python
def calculate_optimal_batch_size(self, complexity, quota_remaining, target_latency):
    """최적 배치 크기 계산"""
    base_size = 50  # 기본 50토큰

    # 복잡도에 따른 조정
    complexity_factor = 1.0 - (complexity * 0.5)

    # 할당량에 따른 조정
    quota_factor = min(quota_remaining / 100.0, 1.0)

    # 목표 지연시간에 따른 조정
    latency_factor = min(10.0 / target_latency, 2.0)

    optimal_size = int(base_size * complexity_factor * quota_factor * latency_factor)
    return max(20, min(optimal_size, 200))  # 20-200 토큰 범위
```

### 2. 병렬 처리 최적화
```python
async def process_multiple_batches(self, batches, task_id):
    """여러 배치 병렬 처리"""
    semaphore = asyncio.Semaphore(3)  # 최대 3개 동시 처리

    async def process_single_batch(batch):
        async with semaphore:
            return await self.translate_batch(batch, task_id)

    tasks = [process_single_batch(batch) for batch in batches]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 결과 집계 및 오류 처리
    successful_results = []
    failed_batches = []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            failed_batches.append(batches[i])
        else:
            successful_results.extend(result)

    # 실패한 배치 재시도
    if failed_batches:
        retry_results = await self.retry_failed_batches(failed_batches, task_id)
        successful_results.extend(retry_results)

    return successful_results
```