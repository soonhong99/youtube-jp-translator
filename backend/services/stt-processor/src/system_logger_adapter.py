import os
import json
import logging
from typing import Any, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from common.utils.system_logger import (
        log_event,
        log_data_flow,
        log_kafka_message,
        log_timeline,
        log_performance,
    )  # type: ignore
except Exception:
    try:
        import redis  # type: ignore
    except Exception:
        redis = None

    REDIS_HOST = os.getenv("SYSTEM_METRICS_REDIS_HOST", os.getenv("REDIS_HOST", "redis"))
    REDIS_PORT = int(os.getenv("SYSTEM_METRICS_REDIS_PORT", os.getenv("REDIS_PORT", 6379)))
    REDIS_DB = int(os.getenv("SYSTEM_METRICS_REDIS_DB", 5))
    KEY_TTL_SECONDS = int(os.getenv("SYSTEM_METRICS_TTL_SECONDS", 86400))

    _client: Optional["redis.Redis"] = None

    def _get_client():
        global _client
        if _client is not None:
            return _client
        if redis is None:
            return None
        try:
            _client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            _client.ping()
            return _client
        except Exception:
            return None

    def log_event(event_type: str, task_id: str, data: Dict[str, Any]) -> bool:
        client = _get_client()
        if client is None or not isinstance(data, dict) or not event_type or not task_id:
            return False
        key = f"{event_type}:{task_id}"
        try:
            if event_type == "performance":
                client.hset(key, mapping={k: str(v) for k, v in data.items()})
                client.expire(key, KEY_TTL_SECONDS)
            else:
                entry = dict(data)
                if "timestamp" not in entry:
                    entry["timestamp"] = datetime.now().strftime("%H:%M:%S")
                client.lpush(key, json.dumps(entry))
                client.ltrim(key, 0, 49)
                client.expire(key, KEY_TTL_SECONDS)
            return True
        except Exception:
            return False

    def log_data_flow(task_id: str, source: str, target: str, message: str, extra: Optional[Dict[str, Any]] = None) -> bool:
        payload: Dict[str, Any] = {"from": source, "to": target, "message": message}
        if extra:
            payload.update(extra)
        return log_event("data_flow", task_id, payload)

    def log_kafka_message(task_id: str, topic: str, message: str, extra: Optional[Dict[str, Any]] = None) -> bool:
        payload: Dict[str, Any] = {"topic": topic, "message": message}
        if extra:
            payload.update(extra)
        return log_event("kafka_message", task_id, payload)

    def log_timeline(task_id: str, agent: str, task: str, progress: int = 0, duration: Optional[float] = None, extra: Optional[Dict[str, Any]] = None) -> bool:
        payload: Dict[str, Any] = {"agent": agent, "task": task, "progress": progress}
        if duration is not None:
            payload["duration"] = str(duration)
        if extra:
            payload.update(extra)
        return log_event("timeline", task_id, payload)

    def log_performance(task_id: str, metrics: Dict[str, Any]) -> bool:
        return log_event("performance", task_id, metrics)

