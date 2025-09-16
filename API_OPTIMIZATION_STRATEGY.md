# API 최적화 및 로드 밸런싱 전략

## 🎯 핵심 최적화 목표
- **API 응답 시간**: 현재 3-5초 → 목표 0.5-1초
- **처리량**: 현재 10 req/min → 목표 100+ req/min
- **비용 효율성**: API 비용 60% 절감
- **장애 허용성**: 99.9% 가용성 달성

## 1. 멀티 모델 API 클라이언트 구현

```python
class MultiModelAPIClient:
    def __init__(self):
        self.models = {
            "gemini_flash": GeminiClient("gemini-1.5-flash-latest"),
            "gemini_pro": GeminiClient("gemini-2.0-flash-exp"),
            "claude_haiku": ClaudeClient("claude-3-haiku-20240307"),
            "openai_mini": OpenAIClient("gpt-4o-mini")
        }
        self.load_balancer = SmartLoadBalancer()
        self.circuit_breaker = AdvancedCircuitBreaker()
        self.cost_optimizer = CostOptimizer()

    async def translate_with_optimization(self, text_batch, task_context):
        """최적화된 번역 실행"""
        # 1. 비용 및 성능 기반 모델 선택
        selected_model = await self.select_optimal_model(text_batch, task_context)

        # 2. 요청 최적화 (배치 크기, 프롬프트 등)
        optimized_request = await self.optimize_request(text_batch, selected_model)

        # 3. Circuit Breaker 체크 및 실행
        try:
            result = await self.execute_with_fallback(optimized_request, selected_model)
            await self.record_success_metrics(selected_model, result)
            return result
        except Exception as e:
            return await self.handle_api_failure(e, text_batch, selected_model)

class SmartLoadBalancer:
    def __init__(self):
        self.model_metrics = ModelMetricsCollector()
        self.cost_calculator = CostCalculator()
        self.performance_predictor = PerformancePredictor()

    async def select_optimal_model(self, text_batch, context):
        """지능형 모델 선택"""
        batch_characteristics = await self.analyze_batch(text_batch)

        # 각 모델별 예상 성능 계산
        model_scores = {}
        for model_name, client in self.models.items():
            # 1. 성능 점수 (속도 + 품질)
            performance_score = await self.performance_predictor.predict_performance(
                model_name, batch_characteristics
            )

            # 2. 비용 점수
            cost_score = await self.cost_calculator.calculate_cost_efficiency(
                model_name, batch_characteristics
            )

            # 3. 가용성 점수 (현재 부하, 할당량 등)
            availability_score = await self.check_availability(model_name)

            # 4. 컨텍스트 적합성 점수
            context_score = await self.calculate_context_fitness(
                model_name, context, batch_characteristics
            )

            # 종합 점수 계산
            total_score = (
                performance_score * 0.35 +
                cost_score * 0.25 +
                availability_score * 0.25 +
                context_score * 0.15
            )

            model_scores[model_name] = {
                "total_score": total_score,
                "performance": performance_score,
                "cost": cost_score,
                "availability": availability_score,
                "context": context_score
            }

        # 최고 점수 모델 선택
        best_model = max(model_scores.items(), key=lambda x: x[1]["total_score"])
        return best_model[0]

class AdvancedCircuitBreaker:
    def __init__(self):
        self.failure_threshold = {
            "gemini_flash": 3,   # 빠른 모델은 낮은 임계값
            "gemini_pro": 5,     # 프리미엄 모델은 높은 임계값
            "claude_haiku": 4,
            "openai_mini": 4
        }
        self.recovery_timeout = 30  # 30초 후 재시도
        self.state_store = {}
        self.health_checker = HealthChecker()

    async def is_available(self, model_name):
        """모델 가용성 체크 (향상된 버전)"""
        state = self.get_model_state(model_name)

        if state["circuit_state"] == "open":
            # 복구 시간 체크
            if time.time() - state["last_failure"] > self.recovery_timeout:
                # 헬스 체크 수행
                if await self.health_checker.check_model_health(model_name):
                    state["circuit_state"] = "half-open"
                    return True
            return False

        return True

    async def execute_with_protection(self, model_name, request_func):
        """Circuit Breaker 보호하에 실행"""
        if not await self.is_available(model_name):
            raise CircuitBreakerOpenException(f"Circuit breaker open for {model_name}")

        start_time = time.time()
        try:
            result = await asyncio.wait_for(request_func(), timeout=30.0)

            # 성공 기록
            await self.record_success(model_name, time.time() - start_time)
            return result

        except asyncio.TimeoutError:
            await self.record_failure(model_name, "timeout")
            raise
        except Exception as e:
            await self.record_failure(model_name, str(e))
            raise

class CostOptimizer:
    def __init__(self):
        self.pricing_model = PricingModel()
        self.budget_manager = BudgetManager()

    async def optimize_request_cost(self, text_batch, model_name):
        """요청 비용 최적화"""
        # 1. 토큰 수 추정
        estimated_tokens = await self.estimate_tokens(text_batch, model_name)

        # 2. 현재 예산 상황 확인
        budget_status = await self.budget_manager.get_budget_status()

        # 3. 배치 크기 최적화
        if budget_status["remaining_budget"] < budget_status["total_budget"] * 0.2:
            # 예산 부족시 더 작은 배치로 분할
            optimal_batch_size = min(len(text_batch), 3)
        else:
            # 여유 있을 때는 더 큰 배치로 효율성 증대
            optimal_batch_size = min(len(text_batch), 8)

        # 4. 프롬프트 최적화
        optimized_prompt = await self.optimize_prompt_length(text_batch, model_name)

        return {
            "batch_size": optimal_batch_size,
            "prompt": optimized_prompt,
            "estimated_cost": await self.calculate_estimated_cost(
                estimated_tokens, model_name
            )
        }

# 2. 캐싱 시스템 구현
class IntelligentCachingSystem:
    def __init__(self):
        self.redis_client = redis.Redis(host='redis', port=6379, db=5)
        self.cache_strategy = AdaptiveCacheStrategy()
        self.similarity_detector = TextSimilarityDetector()

    async def get_cached_translation(self, text, context):
        """지능형 캐시 조회"""
        # 1. 정확한 매치 확인
        exact_cache_key = self.generate_cache_key(text, context)
        cached_result = await self.redis_client.get(exact_cache_key)

        if cached_result:
            return json.loads(cached_result)

        # 2. 유사 텍스트 검색
        similar_translations = await self.find_similar_translations(text, context)

        if similar_translations:
            # 유사도 기반 번역 결과 활용
            best_match = max(similar_translations, key=lambda x: x["similarity"])
            if best_match["similarity"] > 0.85:
                return await self.adapt_translation(best_match, text)

        return None

    async def cache_translation(self, text, translation, context, model_used):
        """번역 결과 캐싱 (메타데이터 포함)"""
        cache_key = self.generate_cache_key(text, context)

        cache_data = {
            "translation": translation,
            "original_text": text,
            "context": context,
            "model_used": model_used,
            "timestamp": time.time(),
            "access_count": 1,
            "quality_score": await self.calculate_quality_score(text, translation)
        }

        # TTL 동적 설정 (품질이 높을수록 더 오래 보관)
        ttl = await self.calculate_dynamic_ttl(cache_data)

        await self.redis_client.setex(
            cache_key,
            ttl,
            json.dumps(cache_data, ensure_ascii=False)
        )

# 3. 배치 처리 최적화
class BatchProcessor:
    def __init__(self):
        self.max_batch_size = 10
        self.min_batch_size = 2
        self.batch_optimizer = BatchOptimizer()

    async def process_dynamic_batches(self, text_queue, task_context):
        """동적 배치 처리"""
        while not text_queue.empty():
            # 1. 현재 상황에 최적화된 배치 크기 결정
            optimal_size = await self.batch_optimizer.calculate_optimal_size(
                queue_size=text_queue.qsize(),
                current_load=await self.get_system_load(),
                task_context=task_context
            )

            # 2. 배치 구성
            batch = []
            for _ in range(min(optimal_size, text_queue.qsize())):
                if not text_queue.empty():
                    batch.append(await text_queue.get())

            if not batch:
                break

            # 3. 배치 처리
            try:
                results = await self.process_batch_with_retry(batch, task_context)
                await self.store_results(results, task_context)
            except Exception as e:
                await self.handle_batch_failure(batch, e, task_context)

class BatchOptimizer:
    def __init__(self):
        self.performance_history = {}
        self.load_predictor = LoadPredictor()

    async def calculate_optimal_size(self, queue_size, current_load, task_context):
        """최적 배치 크기 계산"""
        # 1. 기본 크기 결정
        base_size = 5

        # 2. 대기열 크기 기반 조정
        if queue_size > 20:
            base_size = min(8, base_size + 2)  # 대기열이 클 때 더 큰 배치
        elif queue_size < 5:
            base_size = max(2, base_size - 1)  # 대기열이 작을 때 더 작은 배치

        # 3. 시스템 부하 기반 조정
        if current_load > 0.8:
            base_size = max(2, base_size - 2)  # 부하 높을 때 작은 배치
        elif current_load < 0.3:
            base_size = min(10, base_size + 2)  # 부하 낮을 때 큰 배치

        # 4. 과거 성능 기반 조정
        historical_optimal = await self.get_historical_optimal_size(task_context)
        if historical_optimal:
            base_size = int((base_size + historical_optimal) / 2)

        return max(2, min(10, base_size))

# 4. 병렬 처리 최적화
class ParallelProcessingEngine:
    def __init__(self):
        self.worker_pool = WorkerPool(max_workers=5)
        self.task_scheduler = TaskScheduler()
        self.resource_monitor = ResourceMonitor()

    async def process_parallel_translation(self, text_batches, task_context):
        """병렬 번역 처리"""
        # 1. 리소스 상황 확인
        available_resources = await self.resource_monitor.get_available_resources()

        # 2. 병렬도 계산
        max_parallel = min(
            len(text_batches),
            available_resources["max_concurrent_requests"],
            5  # 하드 리미트
        )

        # 3. 작업 우선순위 결정
        prioritized_batches = await self.task_scheduler.prioritize_batches(
            text_batches, task_context
        )

        # 4. 병렬 실행
        semaphore = asyncio.Semaphore(max_parallel)

        async def process_single_batch(batch):
            async with semaphore:
                return await self.worker_pool.process_batch(batch, task_context)

        # 5. 실행 및 결과 수집
        tasks = [process_single_batch(batch) for batch in prioritized_batches]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 6. 결과 정리 및 오류 처리
        successful_results = []
        failed_batches = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_batches.append(prioritized_batches[i])
            else:
                successful_results.extend(result)

        # 7. 실패한 배치 재시도
        if failed_batches:
            retry_results = await self.retry_failed_batches(failed_batches, task_context)
            successful_results.extend(retry_results)

        return successful_results

# 5. 모니터링 및 자동 튜닝
class PerformanceMonitor:
    def __init__(self):
        self.metrics_collector = MetricsCollector()
        self.auto_tuner = AutoTuner()
        self.alert_manager = AlertManager()

    async def monitor_and_optimize(self, task_id):
        """실시간 모니터링 및 최적화"""
        while True:
            # 1. 메트릭 수집
            metrics = await self.metrics_collector.collect_metrics(task_id)

            # 2. 성능 분석
            analysis = await self.analyze_performance(metrics)

            # 3. 최적화 필요성 판단
            if analysis["needs_optimization"]:
                optimizations = await self.auto_tuner.generate_optimizations(analysis)
                await self.apply_optimizations(optimizations, task_id)

            # 4. 알림 체크
            if analysis["needs_alert"]:
                await self.alert_manager.send_alert(analysis, task_id)

            # 5. 대기
            await asyncio.sleep(10)  # 10초마다 체크
```

## 📊 예상 성능 개선 효과

| 최적화 항목 | 현재 성능 | 목표 성능 | 개선율 |
|------------|----------|----------|--------|
| **API 응답 시간** | 3-5초 | 0.5-1초 | **80% 단축** |
| **처리량** | 10 req/min | 100+ req/min | **10배 증가** |
| **API 비용** | $0.067/10분 | $0.025/10분 | **60% 절감** |
| **첫 결과 시간** | 120초 | 8초 | **93% 단축** |
| **시스템 가용성** | 95% | 99.9% | **4.9% 향상** |