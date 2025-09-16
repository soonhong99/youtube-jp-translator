"""
Phase 3 지능형 버퍼링 시스템 통합
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Any

import httpx
import redis.asyncio as redis
from kafka import KafkaProducer

logger = logging.getLogger(__name__)

class Phase3Integration:
    """Phase 3 시스템 통합 클래스"""

    def __init__(self, redis_client, kafka_producer):
        self.redis_client = redis_client
        self.kafka_producer = kafka_producer

        # 서비스 URL
        self.intelligent_buffering_url = "http://intelligent-buffering:8008"
        self.api_optimization_url = "http://api-optimization:8009"

        # HTTP 클라이언트
        self.http_client = httpx.AsyncClient(timeout=30.0)

        # 피처 플래그
        self.config = {
            'phase3_enabled': True,              # Phase 3 활성화
            'intelligent_buffering_ratio': 0.3,  # 지능형 버퍼링 사용 비율 (30%)
            'api_optimization_ratio': 0.5,       # API 최적화 사용 비율 (50%)
            'fallback_timeout': 5.0,             # 대체 타임아웃 (초)
            'circuit_breaker_threshold': 5,      # 서킷 브레이커 임계값
        }

        # 서킷 브레이커 상태
        self.circuit_breaker_state = {
            'intelligent_buffering': {'failures': 0, 'last_failure': 0, 'is_open': False},
            'api_optimization': {'failures': 0, 'last_failure': 0, 'is_open': False}
        }

        logger.info("✅ Phase3Integration 초기화 완료")

    async def should_use_phase3_buffering(self, task_id: str) -> bool:
        """Phase 3 지능형 버퍼링 사용 여부 결정"""
        try:
            if not self.config['phase3_enabled']:
                return False

            # 서킷 브레이커 확인
            if self._is_circuit_open('intelligent_buffering'):
                return False

            # 해시 기반 일관된 라우팅
            import hashlib
            hash_input = f"{task_id}:{self.config['intelligent_buffering_ratio']}"
            hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
            return (hash_value % 100) < (self.config['intelligent_buffering_ratio'] * 100)

        except Exception as e:
            logger.error(f"❌ Phase 3 버퍼링 결정 실패: {e}")
            return False

    async def should_use_api_optimization(self, task_id: str) -> bool:
        """API 최적화 사용 여부 결정"""
        try:
            if not self.config['phase3_enabled']:
                return False

            # 서킷 브레이커 확인
            if self._is_circuit_open('api_optimization'):
                return False

            # 해시 기반 일관된 라우팅
            import hashlib
            hash_input = f"{task_id}:{self.config['api_optimization_ratio']}"
            hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
            return (hash_value % 100) < (self.config['api_optimization_ratio'] * 100)

        except Exception as e:
            logger.error(f"❌ API 최적화 결정 실패: {e}")
            return False

    async def process_stt_chunk_intelligent(self, task_id: str, chunk_data: Dict) -> Optional[Dict]:
        """지능형 버퍼링을 통한 STT 청크 처리"""
        try:
            # 지능형 버퍼링 서비스로 요청
            buffering_request = {
                'task_id': task_id,
                'text': chunk_data.get('text', ''),
                'start_time': chunk_data.get('start_time', 0.0),
                'end_time': chunk_data.get('end_time', 0.0),
                'chunk_id': chunk_data.get('chunk_id', ''),
                'confidence': chunk_data.get('confidence', 0.0),
                'speaker_id': chunk_data.get('speaker_id'),
                'audio_features': chunk_data.get('audio_features')
            }

            response = await self.http_client.post(
                f"{self.intelligent_buffering_url}/buffer/add",
                json=buffering_request,
                timeout=self.config['fallback_timeout']
            )

            if response.status_code == 200:
                result = response.json()
                self._record_success('intelligent_buffering')

                logger.debug(f"🧠 지능형 버퍼링 처리: {task_id} - 트리거: {result.get('should_trigger', False)}")
                return result
            else:
                raise Exception(f"HTTP {response.status_code}: {response.text}")

        except Exception as e:
            logger.error(f"❌ 지능형 버퍼링 실패: {task_id} - {e}")
            self._record_failure('intelligent_buffering')
            return None

    async def process_translation_optimized(self, task_id: str, translation_data: Dict) -> Optional[Dict]:
        """최적화된 번역 처리"""
        try:
            # API 최적화 서비스로 요청
            translation_request = {
                'task_id': task_id,
                'source_text': translation_data.get('text', ''),
                'target_language': translation_data.get('target_language', 'ko'),
                'priority': translation_data.get('priority', 'normal'),
                'max_cost': translation_data.get('max_cost'),
                'min_quality': translation_data.get('min_quality'),
                'max_latency': translation_data.get('max_latency'),
                'context': translation_data.get('context')
            }

            response = await self.http_client.post(
                f"{self.api_optimization_url}/translate",
                json=translation_request,
                timeout=self.config['fallback_timeout'] * 2  # 번역은 더 오래 걸릴 수 있음
            )

            if response.status_code == 200:
                result = response.json()
                self._record_success('api_optimization')

                logger.debug(f"🚀 최적화 번역 완료: {task_id} - 모델: {result.get('model_used', 'unknown')}")
                return result
            else:
                raise Exception(f"HTTP {response.status_code}: {response.text}")

        except Exception as e:
            logger.error(f"❌ 최적화 번역 실패: {task_id} - {e}")
            self._record_failure('api_optimization')
            return None

    async def get_optimal_model(self, requirements: Dict) -> Optional[Dict]:
        """최적 모델 선택"""
        try:
            response = await self.http_client.post(
                f"{self.api_optimization_url}/model/select",
                json=requirements,
                timeout=2.0
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"⚠️ 모델 선택 실패: HTTP {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"❌ 최적 모델 선택 실패: {e}")
            return None

    async def force_buffer_trigger(self, task_id: str, reason: str = "manual") -> bool:
        """버퍼 강제 트리거"""
        try:
            response = await self.http_client.post(
                f"{self.intelligent_buffering_url}/buffer/force-trigger",
                json={'task_id': task_id, 'reason': reason},
                timeout=5.0
            )

            return response.status_code == 200

        except Exception as e:
            logger.error(f"❌ 버퍼 강제 트리거 실패: {task_id} - {e}")
            return False

    async def get_buffer_status(self, task_id: str) -> Optional[Dict]:
        """버퍼 상태 조회"""
        try:
            response = await self.http_client.get(
                f"{self.intelligent_buffering_url}/buffer/status/{task_id}",
                timeout=2.0
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                logger.warning(f"⚠️ 버퍼 상태 조회 실패: HTTP {response.status_code}")
                return None

        except Exception as e:
            logger.debug(f"버퍼 상태 조회 실패: {task_id} - {e}")
            return None

    async def get_phase3_metrics(self) -> Dict[str, Any]:
        """Phase 3 메트릭 수집"""
        try:
            metrics = {}

            # 지능형 버퍼링 메트릭
            try:
                response = await self.http_client.get(
                    f"{self.intelligent_buffering_url}/metrics",
                    timeout=5.0
                )
                if response.status_code == 200:
                    metrics['intelligent_buffering'] = response.json()
            except Exception as e:
                logger.debug(f"지능형 버퍼링 메트릭 조회 실패: {e}")

            # API 최적화 메트릭
            try:
                response = await self.http_client.get(
                    f"{self.api_optimization_url}/metrics",
                    timeout=5.0
                )
                if response.status_code == 200:
                    metrics['api_optimization'] = response.json()
            except Exception as e:
                logger.debug(f"API 최적화 메트릭 조회 실패: {e}")

            # 통합 메트릭
            metrics['integration'] = {
                'phase3_enabled': self.config['phase3_enabled'],
                'intelligent_buffering_ratio': self.config['intelligent_buffering_ratio'],
                'api_optimization_ratio': self.config['api_optimization_ratio'],
                'circuit_breaker_state': self.circuit_breaker_state
            }

            return metrics

        except Exception as e:
            logger.error(f"❌ Phase 3 메트릭 수집 실패: {e}")
            return {}

    async def get_cost_analysis(self) -> Dict[str, Any]:
        """비용 분석 조회"""
        try:
            response = await self.http_client.get(
                f"{self.api_optimization_url}/cost/analysis",
                timeout=5.0
            )

            if response.status_code == 200:
                return response.json()
            else:
                return {}

        except Exception as e:
            logger.error(f"❌ 비용 분석 조회 실패: {e}")
            return {}

    async def get_cache_stats(self) -> Dict[str, Any]:
        """캐시 통계 조회"""
        try:
            response = await self.http_client.get(
                f"{self.api_optimization_url}/cache/stats",
                timeout=3.0
            )

            if response.status_code == 200:
                return response.json()
            else:
                return {}

        except Exception as e:
            logger.error(f"❌ 캐시 통계 조회 실패: {e}")
            return {}

    def _is_circuit_open(self, service: str) -> bool:
        """서킷 브레이커 상태 확인"""
        try:
            state = self.circuit_breaker_state.get(service, {})

            if not state.get('is_open', False):
                return False

            # 서킷이 열린 지 30초 이상 지났으면 half-open으로 전환
            if time.time() - state.get('last_failure', 0) > 30.0:
                state['is_open'] = False
                state['failures'] = 0
                logger.info(f"🔄 서킷 브레이커 half-open: {service}")
                return False

            return True

        except Exception:
            return False

    def _record_success(self, service: str):
        """성공 기록"""
        try:
            if service in self.circuit_breaker_state:
                self.circuit_breaker_state[service]['failures'] = 0
                self.circuit_breaker_state[service]['is_open'] = False

        except Exception:
            pass

    def _record_failure(self, service: str):
        """실패 기록"""
        try:
            if service not in self.circuit_breaker_state:
                self.circuit_breaker_state[service] = {'failures': 0, 'last_failure': 0, 'is_open': False}

            state = self.circuit_breaker_state[service]
            state['failures'] += 1
            state['last_failure'] = time.time()

            # 임계값 초과 시 서킷 열기
            if state['failures'] >= self.config['circuit_breaker_threshold']:
                state['is_open'] = True
                logger.warning(f"⚠️ 서킷 브레이커 열림: {service} (실패 {state['failures']}회)")

        except Exception as e:
            logger.error(f"❌ 실패 기록 실패: {service} - {e}")

    async def update_phase3_config(self, new_config: Dict[str, Any]) -> bool:
        """Phase 3 설정 업데이트"""
        try:
            for key, value in new_config.items():
                if key in self.config:
                    self.config[key] = value

            # Redis에 설정 저장
            await self.redis_client.set(
                "phase3_config",
                json.dumps(self.config, ensure_ascii=False),
                ex=86400  # 24시간 TTL
            )

            logger.info(f"✅ Phase 3 설정 업데이트: {new_config}")
            return True

        except Exception as e:
            logger.error(f"❌ Phase 3 설정 업데이트 실패: {e}")
            return False

    async def cleanup_old_data(self):
        """오래된 데이터 정리"""
        try:
            # 버퍼 정리 요청
            await self.http_client.post(
                f"{self.intelligent_buffering_url}/buffer/cleanup",
                timeout=10.0
            )

            # 캐시 정리 (선택적)
            # await self.http_client.post(
            #     f"{self.api_optimization_url}/cache/clear",
            #     timeout=10.0
            # )

            logger.debug("🧹 Phase 3 데이터 정리 완료")

        except Exception as e:
            logger.error(f"❌ Phase 3 데이터 정리 실패: {e}")

    async def close(self):
        """리소스 정리"""
        try:
            await self.http_client.aclose()
            logger.info("✅ Phase3Integration 종료 완료")

        except Exception as e:
            logger.error(f"❌ Phase3Integration 종료 실패: {e}")

# 사용 예시
async def example_usage():
    """사용 예시"""
    import redis.asyncio as redis
    from kafka import KafkaProducer

    # Redis 및 Kafka 클라이언트 초기화
    redis_client = redis.Redis(host='localhost', port=6379, db=0)
    kafka_producer = KafkaProducer(
        bootstrap_servers=['localhost:9092'],
        value_serializer=lambda x: json.dumps(x, ensure_ascii=False).encode('utf-8')
    )

    # Phase 3 통합 초기화
    phase3 = Phase3Integration(redis_client, kafka_producer)

    try:
        # STT 청크 처리
        chunk_data = {
            'text': 'こんにちは、世界',
            'start_time': 0.0,
            'end_time': 2.0,
            'chunk_id': 'chunk_001',
            'confidence': 0.95
        }

        if await phase3.should_use_phase3_buffering('task_123'):
            result = await phase3.process_stt_chunk_intelligent('task_123', chunk_data)
            print(f"지능형 버퍼링 결과: {result}")

        # 번역 처리
        translation_data = {
            'text': 'こんにちは、世界',
            'target_language': 'ko',
            'priority': 'normal'
        }

        if await phase3.should_use_api_optimization('task_123'):
            result = await phase3.process_translation_optimized('task_123', translation_data)
            print(f"최적화 번역 결과: {result}")

        # 메트릭 조회
        metrics = await phase3.get_phase3_metrics()
        print(f"Phase 3 메트릭: {metrics}")

    finally:
        await phase3.close()
        await redis_client.close()
        kafka_producer.close()

if __name__ == "__main__":
    asyncio.run(example_usage())