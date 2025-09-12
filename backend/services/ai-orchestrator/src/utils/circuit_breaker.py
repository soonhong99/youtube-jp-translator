"""
API Circuit Breaker Pattern - 할당량 보호 및 장애 격리
"""
import time
import logging
import asyncio
from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass
from enum import Enum
import threading

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"      # 정상 작동
    OPEN = "open"          # 차단 상태 (호출 차단)
    HALF_OPEN = "half_open"  # 테스트 상태 (제한적 호출 허용)

@dataclass
class CircuitBreakerConfig:
    """Circuit Breaker 설정"""
    failure_threshold: int = 5      # 연속 실패 임계치
    recovery_timeout: int = 60      # 복구 대기 시간 (초)
    success_threshold: int = 3      # half-open에서 closed로 전환하기 위한 성공 횟수
    quota_limit: int = 200          # 일일 할당량 제한 (유료 API용 증가)
    quota_window: int = 3600        # 할당량 윈도우 (초, 1시간)
    cost_limit: float = 10.0        # 비용 제한 (USD) - 유료 API용 증가

class APICircuitBreaker:
    """API 호출을 보호하는 Circuit Breaker"""
    
    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0
        self.quota_usage = 0
        self.cost_usage = 0.0
        self.quota_reset_time = time.time() + self.config.quota_window
        self._lock = threading.Lock()
        
        logger.info(f"Circuit Breaker '{name}' initialized: {self.config}")
    
    def _should_reset_quota(self) -> bool:
        """할당량 윈도우 리셋 체크"""
        current_time = time.time()
        if current_time >= self.quota_reset_time:
            self.quota_usage = 0
            self.cost_usage = 0.0
            self.quota_reset_time = current_time + self.config.quota_window
            logger.info(f"Circuit Breaker '{self.name}': Quota window reset")
            return True
        return False
    
    def _can_execute(self) -> tuple[bool, str]:
        """실행 가능 여부 체크"""
        with self._lock:
            self._should_reset_quota()
            
            # 할당량 체크
            if self.quota_usage >= self.config.quota_limit:
                return False, f"Quota limit exceeded: {self.quota_usage}/{self.config.quota_limit}"
            
            # 비용 체크
            if self.cost_usage >= self.config.cost_limit:
                return False, f"Cost limit exceeded: ${self.cost_usage:.4f}/${self.config.cost_limit}"
            
            # Circuit Breaker 상태 체크
            current_time = time.time()
            
            if self.state == CircuitState.OPEN:
                if current_time - self.last_failure_time >= self.config.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                    logger.info(f"Circuit Breaker '{self.name}': OPEN -> HALF_OPEN")
                else:
                    remaining = self.config.recovery_timeout - (current_time - self.last_failure_time)
                    return False, f"Circuit breaker OPEN, recovery in {remaining:.1f}s"
            
            if self.state == CircuitState.HALF_OPEN:
                # half-open에서는 제한적으로만 허용
                if self.quota_usage >= 3:  # half-open에서는 최대 3회만
                    return False, "Circuit breaker HALF_OPEN, limited calls exhausted"
            
            return True, "OK"
    
    def _record_success(self, cost: float = 0.0):
        """성공 기록"""
        with self._lock:
            self.quota_usage += 1
            self.cost_usage += cost
            self.failure_count = 0
            
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self.state = CircuitState.CLOSED
                    logger.info(f"Circuit Breaker '{self.name}': HALF_OPEN -> CLOSED")
    
    def _record_failure(self, error: str):
        """실패 기록"""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.state == CircuitState.CLOSED:
                if self.failure_count >= self.config.failure_threshold:
                    self.state = CircuitState.OPEN
                    logger.warning(f"Circuit Breaker '{self.name}': CLOSED -> OPEN due to {self.failure_count} failures")
            elif self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                logger.warning(f"Circuit Breaker '{self.name}': HALF_OPEN -> OPEN due to failure: {error}")
    
    async def call(self, func: Callable, *args, estimated_cost: float = 0.0, **kwargs) -> Any:
        """Circuit Breaker로 보호된 함수 호출"""
        can_execute, reason = self._can_execute()
        
        if not can_execute:
            logger.warning(f"Circuit Breaker '{self.name}' blocked call: {reason}")
            raise CircuitBreakerOpenException(f"Circuit breaker '{self.name}': {reason}")
        
        start_time = time.time()
        try:
            # 함수 실행
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            # 성공 기록
            execution_time = time.time() - start_time
            self._record_success(estimated_cost)
            
            logger.info(f"Circuit Breaker '{self.name}' SUCCESS: {execution_time:.2f}s, cost: ${estimated_cost:.6f}")
            return result
            
        except Exception as e:
            # 실패 기록
            execution_time = time.time() - start_time
            error_msg = str(e)
            self._record_failure(error_msg)
            
            logger.error(f"Circuit Breaker '{self.name}' FAILURE: {execution_time:.2f}s, error: {error_msg}")
            
            # 할당량 관련 오류는 즉시 OPEN 상태로
            if "429" in error_msg or "quota" in error_msg.lower() or "limit" in error_msg.lower():
                with self._lock:
                    self.state = CircuitState.OPEN
                    logger.error(f"Circuit Breaker '{self.name}': FORCED OPEN due to quota/limit error")
            
            raise
    
    def get_status(self) -> Dict[str, Any]:
        """Circuit Breaker 상태 조회"""
        with self._lock:
            self._should_reset_quota()
            
            remaining_quota = max(0, self.config.quota_limit - self.quota_usage)
            remaining_cost = max(0, self.config.cost_limit - self.cost_usage)
            quota_reset_in = max(0, self.quota_reset_time - time.time())
            
            recovery_time = None
            if self.state == CircuitState.OPEN:
                recovery_time = max(0, self.config.recovery_timeout - (time.time() - self.last_failure_time))
            
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "quota_usage": self.quota_usage,
                "quota_limit": self.config.quota_limit,
                "remaining_quota": remaining_quota,
                "cost_usage": round(self.cost_usage, 6),
                "cost_limit": self.config.cost_limit,
                "remaining_cost": round(remaining_cost, 6),
                "quota_reset_in_seconds": round(quota_reset_in),
                "recovery_time_seconds": round(recovery_time) if recovery_time is not None else None
            }
    
    def force_open(self, reason: str = "Manual intervention"):
        """강제로 OPEN 상태로 전환"""
        with self._lock:
            self.state = CircuitState.OPEN
            self.last_failure_time = time.time()
            logger.warning(f"Circuit Breaker '{self.name}' FORCED OPEN: {reason}")
    
    def force_close(self, reason: str = "Manual intervention"):
        """강제로 CLOSED 상태로 전환"""
        with self._lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            logger.info(f"Circuit Breaker '{self.name}' FORCED CLOSED: {reason}")
    
    def reset_quota(self):
        """할당량 수동 리셋"""
        with self._lock:
            self.quota_usage = 0
            self.cost_usage = 0.0
            self.quota_reset_time = time.time() + self.config.quota_window
            logger.info(f"Circuit Breaker '{self.name}': Manual quota reset")

class CircuitBreakerOpenException(Exception):
    """Circuit Breaker가 OPEN 상태일 때 발생하는 예외"""
    pass

class CircuitBreakerManager:
    """여러 Circuit Breaker를 관리하는 매니저"""
    
    def __init__(self):
        self.breakers: Dict[str, APICircuitBreaker] = {}
        self._lock = threading.Lock()
    
    def get_breaker(self, name: str, config: CircuitBreakerConfig = None) -> APICircuitBreaker:
        """Circuit Breaker 인스턴스 반환 (싱글톤)"""
        with self._lock:
            if name not in self.breakers:
                self.breakers[name] = APICircuitBreaker(name, config)
            return self.breakers[name]
    
    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """모든 Circuit Breaker 상태 조회"""
        with self._lock:
            return {name: breaker.get_status() for name, breaker in self.breakers.items()}
    
    def force_reset_all(self):
        """모든 Circuit Breaker 리셋"""
        with self._lock:
            for breaker in self.breakers.values():
                breaker.force_close("Manager reset")
                breaker.reset_quota()
            logger.info("All circuit breakers reset by manager")

# 전역 매니저 인스턴스
_circuit_breaker_manager = None

def get_circuit_breaker_manager() -> CircuitBreakerManager:
    """Circuit Breaker Manager 싱글톤 반환"""
    global _circuit_breaker_manager
    if _circuit_breaker_manager is None:
        _circuit_breaker_manager = CircuitBreakerManager()
    return _circuit_breaker_manager

def get_circuit_breaker(name: str, config: CircuitBreakerConfig = None) -> APICircuitBreaker:
    """Circuit Breaker 인스턴스 반환 (편의 함수)"""
    return get_circuit_breaker_manager().get_breaker(name, config)