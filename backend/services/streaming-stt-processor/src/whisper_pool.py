"""
Whisper Model Pool
3개 Whisper 모델 인스턴스를 풀링하여 병렬 처리 최적화
"""

import asyncio
import logging
import os
import time
from typing import List, Optional, Dict, Any
import threading
from contextlib import asynccontextmanager

from faster_whisper import WhisperModel
import torch

logger = logging.getLogger(__name__)

class WhisperModelPool:
    """Whisper 모델 풀 관리 클래스"""

    def __init__(
        self,
        model_name: str = "base",
        pool_size: int = 3,
        device: str = "auto"
    ):
        self.model_name = model_name
        self.pool_size = pool_size
        self.device = self._determine_device(device)
        self.cpu_threads = self._determine_cpu_threads()

        # 모델 풀
        self.models: List[WhisperModel] = []
        self.available_models: asyncio.Queue = None
        self.model_lock = asyncio.Lock()

        # 초기화 상태
        self.is_initialized = False
        self.initialization_error = None

        # 메트릭
        self.metrics = {
            "total_requests": 0,
            "active_models": 0,
            "model_usage": {},
            "average_wait_time": 0.0,
            "last_reset_time": time.time()
        }

        # 모델별 사용 통계
        self.model_stats = {}

    def _determine_device(self, device: str) -> str:
        """최적의 디바이스 결정"""
        if device == "auto":
            if torch.cuda.is_available():
                return "cuda"
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                return "mps"
            else:
                return "cpu"
        return device

    def _determine_cpu_threads(self) -> int:
        """모델당 CPU 스레드 수 결정 - 성능 최적화"""
        if self.device != "cpu":
            return 0

        cpu_count = os.cpu_count() or 1
        if cpu_count <= 1:
            return 1

        # 성능 최적화: 더 많은 스레드 할당
        # 8코어 시스템에서 3모델 -> 4스레드/모델 (오버커밋 허용)
        if cpu_count >= 8:
            # 고성능 시스템: 코어 수의 50-75% 활용
            threads_per_model = max(3, min(6, (cpu_count * 3) // (self.pool_size * 2)))
        elif cpu_count >= 4:
            # 중간 성능: 코어 수의 75% 활용
            threads_per_model = max(2, (cpu_count * 3) // 4)
        else:
            # 저성능: 기존 로직
            threads_per_model = max(1, cpu_count // max(1, self.pool_size))

        logger.info(f"🧵 CPU 스레드 최적화: {cpu_count}코어 → {threads_per_model}스레드/모델 (총 {self.pool_size}모델)")
        return threads_per_model

    async def initialize(self):
        """모델 풀 초기화"""
        try:
            logger.info(f"🚀 Whisper 모델 풀 초기화 시작: {self.model_name} x{self.pool_size} on {self.device}")

            self.available_models = asyncio.Queue(maxsize=self.pool_size)

            # 모델들을 별도 스레드에서 로드 (CPU 집약적 작업)
            loop = asyncio.get_event_loop()
            models = await loop.run_in_executor(
                None,
                self._load_models_sync
            )

            # 큐에 모델들 추가
            for i, model in enumerate(models):
                await self.available_models.put(model)
                self.model_stats[f"model_{i}"] = {
                    "usage_count": 0,
                    "total_processing_time": 0.0,
                    "last_used": time.time()
                }

            self.models = models
            self.is_initialized = True

            logger.info(f"✅ Whisper 모델 풀 초기화 완료: {len(self.models)}개 모델")

        except Exception as e:
            self.initialization_error = str(e)
            logger.error(f"❌ Whisper 모델 풀 초기화 실패: {e}")
            raise

    def _load_models_sync(self) -> List[WhisperModel]:
        """동기적으로 모델들 로드"""
        models = []

        try:
            for i in range(self.pool_size):
                logger.info(f"📥 Whisper 모델 {i+1}/{self.pool_size} 로딩 중...")

                # 성능 최적화된 Whisper 모델 설정
                model_kwargs = {
                    "model_size_or_path": self.model_name,
                    "device": self.device,
                    "compute_type": "float16" if self.device != "cpu" else "int8",
                    "cpu_threads": self.cpu_threads if self.device == "cpu" else 0,
                    # 성능 최적화 옵션들
                    "num_workers": 1,  # 모델당 워커 수
                    "download_root": None,  # 기본 캐시 디렉토리 사용
                    "local_files_only": False,  # 온라인 다운로드 허용
                }

                # CPU 최적화 추가 설정
                if self.device == "cpu" and self.cpu_threads > 0:
                    # OpenMP 스레드 수 제한 (너무 많으면 오히려 느려짐)
                    import os
                    os.environ["OMP_NUM_THREADS"] = str(min(self.cpu_threads, 4))
                    os.environ["MKL_NUM_THREADS"] = str(min(self.cpu_threads, 4))

                logger.info(f"📥 모델 {i+1} 최적화 설정: {self.cpu_threads}스레드, {model_kwargs['compute_type']}")

                model = WhisperModel(**model_kwargs)

                models.append(model)
                logger.info(f"✅ 모델 {i+1} 로딩 완료")

            return models

        except Exception as e:
            logger.error(f"❌ 모델 로딩 실패: {e}")
            raise

    async def get_model(self, timeout: float = 30.0) -> WhisperModel:
        """모델 풀에서 모델 가져오기"""
        if not self.is_initialized:
            raise RuntimeError("모델 풀이 초기화되지 않았습니다")

        start_time = time.time()

        try:
            # 타임아웃과 함께 모델 대기
            model = await asyncio.wait_for(
                self.available_models.get(),
                timeout=timeout
            )

            wait_time = time.time() - start_time

            # 메트릭 업데이트
            self.metrics["total_requests"] += 1
            self.metrics["active_models"] += 1

            # 평균 대기 시간 업데이트
            total_requests = self.metrics["total_requests"]
            current_avg = self.metrics["average_wait_time"]
            self.metrics["average_wait_time"] = (
                (current_avg * (total_requests - 1) + wait_time) / total_requests
            )

            logger.debug(f"🎯 모델 할당 완료 (대기 시간: {wait_time:.3f}초)")

            return model

        except asyncio.TimeoutError:
            logger.error(f"❌ 모델 할당 타임아웃 ({timeout}초)")
            raise RuntimeError(f"모델 할당 타임아웃: {timeout}초")

    async def return_model(self, model: WhisperModel):
        """모델 풀에 모델 반환"""
        if not self.is_initialized:
            return

        try:
            # 모델 상태 검증
            if model not in self.models:
                logger.warning("⚠️ 풀에 속하지 않은 모델 반환 시도")
                return

            # 큐에 모델 반환
            await self.available_models.put(model)

            # 메트릭 업데이트
            self.metrics["active_models"] = max(0, self.metrics["active_models"] - 1)

            logger.debug("🔄 모델 반환 완료")

        except Exception as e:
            logger.error(f"❌ 모델 반환 실패: {e}")

    @asynccontextmanager
    async def get_model_context(self, timeout: float = 30.0):
        """컨텍스트 매니저로 모델 사용"""
        model = None
        try:
            model = await self.get_model(timeout)
            yield model
        finally:
            if model:
                await self.return_model(model)

    async def get_status(self) -> Dict[str, Any]:
        """모델 풀 상태 조회"""
        if not self.is_initialized:
            return {
                "initialized": False,
                "error": self.initialization_error
            }

        available_count = self.available_models.qsize()
        active_count = self.pool_size - available_count

        return {
            "initialized": True,
            "model_name": self.model_name,
            "pool_size": self.pool_size,
            "device": self.device,
            "available_models": available_count,
            "active_models": active_count,
            "utilization": (active_count / self.pool_size) * 100
        }

    async def get_metrics(self) -> Dict[str, Any]:
        """성능 메트릭 조회"""
        uptime = time.time() - self.metrics["last_reset_time"]

        return {
            "uptime_seconds": uptime,
            "total_requests": self.metrics["total_requests"],
            "active_models": self.metrics["active_models"],
            "average_wait_time": self.metrics["average_wait_time"],
            "requests_per_second": self.metrics["total_requests"] / uptime if uptime > 0 else 0,
            "model_stats": self.model_stats.copy()
        }

    async def health_check(self) -> Dict[str, Any]:
        """헬스 체크"""
        try:
            if not self.is_initialized:
                return {
                    "status": "unhealthy",
                    "reason": "모델 풀이 초기화되지 않았습니다",
                    "error": self.initialization_error
                }

            # 빠른 모델 테스트 (타임아웃 5초)
            start_time = time.time()
            try:
                async with self.get_model_context(timeout=5.0) as model:
                    # 간단한 동작 테스트
                    pass

                response_time = time.time() - start_time

                return {
                    "status": "healthy",
                    "response_time": response_time,
                    "available_models": self.available_models.qsize(),
                    "total_models": self.pool_size
                }

            except Exception as e:
                return {
                    "status": "unhealthy",
                    "reason": "모델 할당 실패",
                    "error": str(e)
                }

        except Exception as e:
            return {
                "status": "unhealthy",
                "reason": "헬스 체크 실패",
                "error": str(e)
            }

    async def reset_metrics(self):
        """메트릭 리셋"""
        self.metrics = {
            "total_requests": 0,
            "active_models": self.metrics["active_models"],  # 현재 활성 모델 수 유지
            "model_usage": {},
            "average_wait_time": 0.0,
            "last_reset_time": time.time()
        }

        # 모델별 통계 리셋
        for model_id in self.model_stats:
            self.model_stats[model_id].update({
                "usage_count": 0,
                "total_processing_time": 0.0
            })

        logger.info("🔄 Whisper 모델 풀 메트릭 리셋 완료")

    async def cleanup(self):
        """모델 풀 정리"""
        try:
            self.is_initialized = False

            # 모든 모델 해제
            while not self.available_models.empty():
                try:
                    model = await asyncio.wait_for(
                        self.available_models.get(),
                        timeout=1.0
                    )
                    # 모델 객체 정리 (faster-whisper는 명시적 cleanup 불필요)
                    del model
                except asyncio.TimeoutError:
                    break
                except Exception as e:
                    logger.warning(f"⚠️ 모델 정리 중 오류: {e}")

            self.models.clear()
            logger.info("✅ Whisper 모델 풀 정리 완료")

        except Exception as e:
            logger.error(f"❌ 모델 풀 정리 실패: {e}")

    def __repr__(self):
        return f"WhisperModelPool(model={self.model_name}, size={self.pool_size}, device={self.device})"
