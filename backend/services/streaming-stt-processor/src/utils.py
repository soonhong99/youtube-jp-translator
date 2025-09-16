"""
Streaming STT Processor Utilities
"""

import logging
import sys
import os
import asyncio
import time
from typing import Dict, Any, Optional
from pathlib import Path

def setup_logging(log_level: str = "INFO"):
    """로깅 설정"""
    # 로그 레벨 설정
    level = getattr(logging, log_level.upper(), logging.INFO)

    # 로그 포맷 설정
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )

    # 콘솔 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)

    # 라이브러리 로거 레벨 조정
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)
    logging.getLogger("torch").setLevel(logging.WARNING)
    logging.getLogger("kafka").setLevel(logging.WARNING)

async def health_check(whisper_pool=None, streaming_worker=None) -> Dict[str, Any]:
    """종합 헬스 체크"""
    start_time = time.time()
    health_status = {
        "status": "healthy",
        "timestamp": start_time,
        "checks": {},
        "response_time": 0.0
    }

    try:
        # Whisper 모델 풀 체크
        if whisper_pool:
            pool_health = await whisper_pool.health_check()
            health_status["checks"]["whisper_pool"] = pool_health

            if pool_health["status"] != "healthy":
                health_status["status"] = "unhealthy"

        # 스트리밍 워커 체크
        if streaming_worker:
            worker_status = await streaming_worker.get_status()
            health_status["checks"]["streaming_worker"] = {
                "status": "healthy" if worker_status["is_running"] else "unhealthy",
                "is_running": worker_status["is_running"],
                "active_tasks": worker_status["active_tasks"]
            }

            if not worker_status["is_running"]:
                health_status["status"] = "unhealthy"

        # 시스템 리소스 체크
        system_health = await check_system_resources()
        health_status["checks"]["system"] = system_health

        if system_health["status"] != "healthy":
            health_status["status"] = "degraded"

        # 응답 시간 계산
        health_status["response_time"] = time.time() - start_time

        return health_status

    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": start_time,
            "error": str(e),
            "response_time": time.time() - start_time
        }

async def check_system_resources() -> Dict[str, Any]:
    """시스템 리소스 체크"""
    try:
        import psutil

        # CPU 사용률
        cpu_percent = psutil.cpu_percent(interval=1)

        # 메모리 사용률
        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        # 디스크 사용률 (임시 디렉토리)
        temp_dir = Path("/tmp")
        if temp_dir.exists():
            disk_usage = psutil.disk_usage(str(temp_dir))
            disk_percent = (disk_usage.used / disk_usage.total) * 100
        else:
            disk_percent = 0

        # 프로세스 정보
        process = psutil.Process()
        process_memory = process.memory_info().rss / 1024 / 1024  # MB

        # 상태 판정
        status = "healthy"
        if cpu_percent > 90 or memory_percent > 90 or disk_percent > 90:
            status = "unhealthy"
        elif cpu_percent > 70 or memory_percent > 70 or disk_percent > 70:
            status = "degraded"

        return {
            "status": status,
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "disk_percent": disk_percent,
            "process_memory_mb": process_memory,
            "available_memory_gb": memory.available / 1024 / 1024 / 1024
        }

    except ImportError:
        return {
            "status": "unknown",
            "error": "psutil not available"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

def ensure_directory(directory_path: str) -> bool:
    """디렉토리 존재 확인 및 생성"""
    try:
        Path(directory_path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False

def get_file_size_mb(file_path: str) -> float:
    """파일 크기를 MB 단위로 반환"""
    try:
        return os.path.getsize(file_path) / 1024 / 1024
    except Exception:
        return 0.0

def validate_audio_file_format(file_path: str) -> bool:
    """오디오 파일 포맷 검증"""
    supported_formats = {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.mp4'}
    file_extension = Path(file_path).suffix.lower()
    return file_extension in supported_formats

async def cleanup_old_temp_files(temp_dir: str, max_age_hours: int = 24):
    """오래된 임시 파일들 정리"""
    try:
        temp_path = Path(temp_dir)
        if not temp_path.exists():
            return

        current_time = time.time()
        max_age_seconds = max_age_hours * 3600

        removed_count = 0
        total_size_mb = 0

        for file_path in temp_path.glob("**/*"):
            if file_path.is_file():
                file_age = current_time - file_path.stat().st_mtime

                if file_age > max_age_seconds:
                    try:
                        file_size = file_path.stat().st_size / 1024 / 1024
                        file_path.unlink()
                        removed_count += 1
                        total_size_mb += file_size
                    except Exception as e:
                        logging.warning(f"임시 파일 삭제 실패: {file_path}, {e}")

        if removed_count > 0:
            logging.info(f"임시 파일 정리 완료: {removed_count}개 파일, {total_size_mb:.2f}MB")

    except Exception as e:
        logging.error(f"임시 파일 정리 실패: {e}")

class AsyncTimer:
    """비동기 타이머 클래스"""

    def __init__(self):
        self.start_time = None
        self.end_time = None

    def start(self):
        """타이머 시작"""
        self.start_time = time.time()

    def stop(self):
        """타이머 종료"""
        self.end_time = time.time()

    @property
    def elapsed(self) -> float:
        """경과 시간 반환"""
        if self.start_time is None:
            return 0.0

        end = self.end_time if self.end_time else time.time()
        return end - self.start_time

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

class RateLimiter:
    """요청 속도 제한 클래스"""

    def __init__(self, max_requests: int, time_window: float):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []

    async def acquire(self) -> bool:
        """요청 허용 여부 확인"""
        current_time = time.time()

        # 시간 윈도우 밖의 요청들 제거
        self.requests = [
            req_time for req_time in self.requests
            if current_time - req_time < self.time_window
        ]

        # 요청 한도 확인
        if len(self.requests) < self.max_requests:
            self.requests.append(current_time)
            return True

        return False

async def retry_async(
    func,
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """비동기 함수 재시도"""
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func()
            else:
                return func()

        except exceptions as e:
            last_exception = e

            if attempt < max_retries:
                wait_time = delay * (backoff_factor ** attempt)
                logging.warning(
                    f"재시도 {attempt + 1}/{max_retries}: {e}, "
                    f"{wait_time:.2f}초 후 재시도"
                )
                await asyncio.sleep(wait_time)
            else:
                logging.error(f"최대 재시도 횟수 초과: {e}")

    raise last_exception

def format_duration(seconds: float) -> str:
    """초를 사람이 읽기 쉬운 형태로 변환"""
    if seconds < 60:
        return f"{seconds:.1f}초"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        remaining_seconds = seconds % 60
        return f"{minutes}분 {remaining_seconds:.1f}초"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        remaining_seconds = seconds % 60
        return f"{hours}시간 {minutes}분 {remaining_seconds:.1f}초"

def format_file_size(bytes_size: int) -> str:
    """바이트를 사람이 읽기 쉬운 형태로 변환"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f}{unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f}TB"