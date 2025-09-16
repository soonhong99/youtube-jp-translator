"""
Streaming Handler for API Gateway
스트리밍 요청 처리 및 라우팅 관리
"""

import asyncio
import os
import json
import logging
import time
from typing import Dict, List, Optional, Any
import hashlib
import threading

import redis.asyncio as redis
from kafka import KafkaProducer, KafkaConsumer
from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from prometheus_client import Counter

logger = logging.getLogger(__name__)

# Kafka 설정 (컨테이너 환경 기본값)
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

# Prometheus metrics
buffer_trigger_total = Counter('buffer_trigger_total', 'Total buffer triggers', ['reason'])
optimized_results_forwarded_total = Counter('optimized_results_forwarded_total', 'Optimized translation results forwarded')

class StreamingRequest(BaseModel):
    """스트리밍 요청 모델"""
    task_id: str
    audio_file_path: str
    mode: str = "streaming"
    priority: int = 1
    max_latency: int = 10
    quality_requirement: float = 0.8
    context: Optional[Dict] = None
    # Optional, allow caller to tweak chunking
    chunk_duration: Optional[float] = None
    overlap_duration: Optional[float] = None

# Backward-compatible request model used by API Gateway route
class StreamingTranslationRequest(StreamingRequest):
    """Alias of StreamingRequest for translation route compatibility."""
    pass

class FeatureFlag:
    """피처 플래그 관리 클래스"""

    def __init__(self, redis_client):
        self.redis_client = redis_client

    async def get_rollout_percentage(self) -> int:
        """현재 롤아웃 비율 조회"""
        try:
            percentage = await self.redis_client.get("streaming_rollout_percentage")
            return int(percentage) if percentage else 0
        except Exception as e:
            logger.error(f"❌ 롤아웃 비율 조회 실패: {e}")
            return 0

    async def set_rollout_percentage(self, percentage: int) -> bool:
        """롤아웃 비율 설정"""
        try:
            if not 0 <= percentage <= 100:
                raise ValueError("롤아웃 비율은 0-100 사이여야 합니다")

            await self.redis_client.set("streaming_rollout_percentage", percentage)
            await self.redis_client.set("streaming_rollout_updated", time.time())

            logger.info(f"🎯 스트리밍 롤아웃 비율 설정: {percentage}%")
            return True

        except Exception as e:
            logger.error(f"❌ 롤아웃 비율 설정 실패: {e}")
            return False

    async def should_use_streaming(self, task_id: str) -> bool:
        """작업이 스트리밍 모드를 사용해야 하는지 결정"""
        try:
            percentage = await self.get_rollout_percentage()

            if percentage == 0:
                return False
            elif percentage == 100:
                return True

            # 일관된 라우팅을 위한 해시 기반 결정
            hash_input = f"{task_id}:{percentage}"
            hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
            return (hash_value % 100) < percentage

        except Exception as e:
            logger.error(f"❌ 스트리밍 모드 결정 실패: {e}")
            return False

class StreamingWebSocketManager:
    """스트리밍 WebSocket 연결 관리"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.task_connections: Dict[str, str] = {}  # task_id -> connection_id

    async def connect(self, websocket: WebSocket, connection_id: str):
        """WebSocket 연결"""
        await websocket.accept()
        self.active_connections[connection_id] = websocket
        logger.info(f"🔌 WebSocket 연결: {connection_id}")

    def disconnect(self, connection_id: str):
        """WebSocket 연결 해제"""
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]

        # 작업 연결 정리
        task_to_remove = None
        for task_id, conn_id in self.task_connections.items():
            if conn_id == connection_id:
                task_to_remove = task_id
                break

        if task_to_remove:
            del self.task_connections[task_to_remove]

        logger.info(f"🔌 WebSocket 연결 해제: {connection_id}")

    async def bind_task(self, task_id: str, connection_id: str):
        """작업과 WebSocket 연결 바인딩"""
        self.task_connections[task_id] = connection_id
        logger.debug(f"🔗 작업 바인딩: {task_id} -> {connection_id}")

    async def send_to_task(self, task_id: str, message: Dict):
        """특정 작업에 메시지 전송"""
        connection_id = self.task_connections.get(task_id)
        if connection_id and connection_id in self.active_connections:
            try:
                websocket = self.active_connections[connection_id]
                await websocket.send_json(message)
                logger.debug(f"📤 메시지 전송: {task_id}")
                return True
            except Exception as e:
                logger.error(f"❌ 메시지 전송 실패: {task_id} - {e}")
                # 연결이 끊어진 경우 정리
                self.disconnect(connection_id)

        return False

    async def broadcast(self, message: Dict):
        """모든 연결에 브로드캐스트"""
        disconnected = []

        for connection_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.append(connection_id)

        # 끊어진 연결 정리
        for connection_id in disconnected:
            self.disconnect(connection_id)

class StreamingHandler:
    """스트리밍 요청 처리 핸들러"""

    def __init__(self, redis_client, kafka_producer, phase3_integration=None):
        self.redis_client = redis_client
        self.kafka_producer = kafka_producer
        # Optional Phase 3 integration (intelligent buffering + API optimization)
        self.phase3 = phase3_integration
        self.feature_flag = FeatureFlag(redis_client)
        self.websocket_manager = StreamingWebSocketManager()

        # Kafka 컨슈머는 이벤트 루프를 막지 않도록 별도 스레드에서 실행
        self.kafka_consumer = None
        self.consumer_thread = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.is_running = False

    async def start(self):
        """스트리밍 핸들러 시작"""
        try:
            self.is_running = True

            # 현재 이벤트 루프 저장 (스레드에서 코루틴 실행에 사용)
            self.loop = asyncio.get_running_loop()

            # Kafka 컨슈머를 별도 스레드에서 시작 (동기 루프)
            self.consumer_thread = threading.Thread(
                target=self._kafka_consume_loop,
                name="kafka-consumer-thread",
                daemon=True,
            )
            self.consumer_thread.start()

            logger.info("✅ 스트리밍 핸들러 시작 완료")

        except Exception as e:
            logger.error(f"❌ 스트리밍 핸들러 시작 실패: {e}")
            raise

    async def stop(self):
        """스트리밍 핸들러 종료"""
        self.is_running = False

        if self.kafka_consumer:
            try:
                self.kafka_consumer.close()
            except Exception:
                pass

        if self.consumer_thread and self.consumer_thread.is_alive():
            try:
                self.consumer_thread.join(timeout=2)
            except Exception:
                pass

        logger.info("✅ 스트리밍 핸들러 종료 완료")

    def _kafka_consume_loop(self):
        """Kafka 컨슈머 루프 (블로킹) - 별도 스레드에서 실행"""
        try:
            from kafka import KafkaConsumer

            self.kafka_consumer = KafkaConsumer(
                'stt_chunks',
                'translation_results',
                'realtime_results',
                'streaming_control',
                'optimized_translation_results',
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS.split(','),
                group_id='api-gateway-streaming',
                auto_offset_reset='latest',
                value_deserializer=lambda x: json.loads(x.decode('utf-8'))
            )

            logger.info("🎧 Kafka 컨슈머 시작 (스레드)")

            for message in self.kafka_consumer:
                if not self.is_running:
                    break

                try:
                    if self.loop and self.loop.is_running():
                        # 메시지 처리를 이벤트 루프에 위임
                        asyncio.run_coroutine_threadsafe(
                            self._process_kafka_message(message),
                            self.loop,
                        )
                except Exception as e:
                    logger.error(f"❌ Kafka 메시지 처리 실패: {e}")

        except Exception as e:
            logger.error(f"❌ Kafka 컨슈머 오류(스레드): {e}")

    async def _process_kafka_message(self, message):
        """Kafka 메시지 처리"""
        topic = message.topic
        data = message.value
        task_id = data.get('task_id')

        if not task_id:
            return

        # 메시지 타입별 처리
        if topic == 'stt_chunks':
            await self._handle_stt_chunk(data)
        elif topic == 'translation_results':
            await self._handle_translation_result(data)
        elif topic == 'realtime_results':
            await self._handle_realtime_result(data)
        elif topic == 'streaming_control':
            await self._handle_streaming_control(data)
        elif topic == 'optimized_translation_results':
            await self._handle_optimized_translation_result(data)

    async def _handle_stt_chunk(self, data):
        """STT 청크 처리"""
        task_id = data.get('task_id')
        chunk_data = data.get('data', {})

        message = {
            "type": "stt_chunk",
            "task_id": task_id,
            "chunk_id": chunk_data.get('chunk_id'),
            "text": chunk_data.get('text'),
            "start_time": chunk_data.get('start_time'),
            "end_time": chunk_data.get('end_time'),
            "confidence": chunk_data.get('confidence'),
            "timestamp": time.time()
        }

        # 1) WS로 바로 전달
        await self.websocket_manager.send_to_task(task_id, message)

        # 2) Phase 3 지능형 버퍼링 적용 (가능한 경우)
        try:
            if self.phase3 and await self.phase3.should_use_phase3_buffering(task_id):
                buffering_result = await self.phase3.process_stt_chunk_intelligent(task_id, chunk_data)
                should_trigger = bool(buffering_result and buffering_result.get('should_trigger'))

                # Intelligent Buffering 비가용/무응답 시 주기적(10청크마다) 트리거로 폴백
                if not should_trigger:
                    c_id = str(chunk_data.get('chunk_id', ''))
                    try:
                        idx = int(c_id.rsplit('_', 1)[-1]) if '_' in c_id else 0
                    except Exception:
                        idx = 0
                    should_trigger = (idx % 10 == 0)

                if should_trigger:
                    payload = {
                        'task_id': task_id,
                        'chunk_id': chunk_data.get('chunk_id'),
                        'text': chunk_data.get('text', ''),
                        'priority': 'normal',
                        'reason': (buffering_result or {}).get('trigger_reason', 'buffering_or_periodic')
                    }
                    self.kafka_producer.send('intelligent_translation_requests', key=task_id, value=payload)
                    try:
                        buffer_trigger_total.labels(reason=payload.get('reason','unknown')).inc()
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"❌ Phase 3 buffering flow failed for {task_id}: {e}")

    async def _handle_translation_result(self, data):
        """번역 결과 처리"""
        task_id = data.get('task_id')

        message = {
            "type": "translation_result",
            "task_id": task_id,
            "chunk_id": data.get('chunk_id'),
            "original_text": data.get('original_text'),
            "translated_text": data.get('translated_text'),
            "worker_used": data.get('worker_used'),
            "processing_time": data.get('processing_time'),
            "timestamp": time.time()
        }

        await self.websocket_manager.send_to_task(task_id, message)

    async def _handle_realtime_result(self, data):
        """실시간 결과 처리"""
        task_id = data.get('task_id')

        message = {
            "type": "realtime_result",
            "task_id": task_id,
            "sentences": data.get('sentences', []),
            "progress": data.get('progress', 0),
            "estimated_remaining": data.get('estimated_remaining', 0),
            "timestamp": time.time()
        }

        await self.websocket_manager.send_to_task(task_id, message)

    async def _handle_optimized_translation_result(self, data):
        """API 최적화 번역 결과 처리"""
        try:
            task_id = data.get('task_id')
            result = data.get('result', {})
            message = {
                "type": "optimized_translation_result",
                "task_id": task_id,
                "translated_text": result.get('translated_text'),
                "model_used": result.get('model_used'),
                "processing_time": result.get('processing_time'),
                "cost": result.get('cost'),
                "cache_hit": result.get('cache_hit', False),
                "timestamp": time.time()
            }
            await self.websocket_manager.send_to_task(task_id, message)
            try:
                optimized_results_forwarded_total.inc()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"❌ Optimized translation result handling failed: {e}")

    async def _handle_streaming_control(self, data):
        """스트리밍 제어 메시지 처리"""
        message_type = data.get('type')

        if message_type == 'stt_progress':
            await self._handle_stt_progress(data)
        elif message_type == 'task_complete':
            await self._handle_task_complete(data)
        elif message_type == 'task_error':
            await self._handle_task_error(data)

    async def _handle_stt_progress(self, data):
        """STT 진행 상황 처리"""
        progress_data = data.get('data', {})
        task_id = progress_data.get('task_id')

        message = {
            "type": "stt_progress",
            "task_id": task_id,
            "total_chunks": progress_data.get('total_chunks'),
            "processed_chunks": progress_data.get('processed_chunks'),
            "progress_percent": progress_data.get('progress_percent'),
            "status": progress_data.get('status'),
            "timestamp": time.time()
        }

        await self.websocket_manager.send_to_task(task_id, message)
        # Redis에 진행상황 병합 저장 (상태 조회 강화를 위해)
        try:
            key = f"streaming_task:{task_id}"
            raw = await self.redis_client.get(key)
            state = json.loads(raw) if raw else {"task_id": task_id, "status": "processing"}
            state.update({
                "processed_chunks": progress_data.get('processed_chunks'),
                "total_chunks": progress_data.get('total_chunks'),
                "progress_percent": progress_data.get('progress_percent'),
                "updated_at": time.time()
            })
            await self.redis_client.setex(key, 3600, json.dumps(state, ensure_ascii=False))
        except Exception as e:
            logger.debug(f"상태 업데이트 실패: {e}")

    async def _handle_task_complete(self, data):
        """작업 완료 처리"""
        task_id = data.get('task_id')

        message = {
            "type": "task_complete",
            "task_id": task_id,
            "final_results": data.get('final_results', []),
            "processing_time": data.get('processing_time'),
            "timestamp": time.time()
        }

        await self.websocket_manager.send_to_task(task_id, message)
        # 상태 완료 저장
        try:
            key = f"streaming_task:{task_id}"
            raw = await self.redis_client.get(key)
            state = json.loads(raw) if raw else {"task_id": task_id}
            state.update({"status": "completed", "processing_time": data.get('processing_time'), "updated_at": time.time()})
            await self.redis_client.setex(key, 3600, json.dumps(state, ensure_ascii=False))
        except Exception:
            pass

        # 작업 완료 후 연결 정리
        await asyncio.sleep(5)  # 5초 후 정리
        if task_id in self.websocket_manager.task_connections:
            connection_id = self.websocket_manager.task_connections[task_id]
            self.websocket_manager.disconnect(connection_id)

    async def _handle_task_error(self, data):
        """작업 오류 처리"""
        task_id = data.get('task_id')

        message = {
            "type": "task_error",
            "task_id": task_id,
            "error_message": data.get('error_message'),
            "error_code": data.get('error_code'),
            "timestamp": time.time()
        }

        await self.websocket_manager.send_to_task(task_id, message)
        # 상태 에러 저장
        try:
            key = f"streaming_task:{task_id}"
            raw = await self.redis_client.get(key)
            state = json.loads(raw) if raw else {"task_id": task_id}
            state.update({"status": "failed", "error": data.get('error_message'), "updated_at": time.time()})
            await self.redis_client.setex(key, 3600, json.dumps(state, ensure_ascii=False))
        except Exception:
            pass

    async def process_streaming_request(self, request: StreamingRequest) -> Dict[str, Any]:
        """스트리밍 요청 처리"""
        try:
            logger.info(f"🚀 스트리밍 요청 처리 시작: {request.task_id}")

            # 피처 플래그 확인
            use_streaming = await self.feature_flag.should_use_streaming(request.task_id)

            if not use_streaming:
                logger.info(f"🔄 Legacy 모드로 라우팅: {request.task_id}")
                return await self._route_to_legacy(request)

            # 스트리밍 모드 처리
            return await self._process_streaming_mode(request)

        except Exception as e:
            logger.error(f"❌ 스트리밍 요청 처리 실패: {request.task_id} - {e}")
            raise HTTPException(status_code=500, detail=f"스트리밍 처리 실패: {str(e)}")

    async def _route_to_legacy(self, request: StreamingRequest) -> Dict[str, Any]:
        """Legacy 시스템으로 라우팅"""
        # 기존 STT 프로세서로 요청 전송
        legacy_request = {
            "task_id": request.task_id,
            "audio_file_path": request.audio_file_path,
            "language": "ja",
            "processing_mode": "batch"
        }

        # Kafka로 legacy 요청 전송
        self.kafka_producer.send(
            'stt_requests',
            key=request.task_id,
            value=legacy_request
        )

        return {
            "task_id": request.task_id,
            "mode": "legacy",
            "status": "processing",
            "message": "Legacy 모드로 처리 중입니다"
        }

    async def _process_streaming_mode(self, request: StreamingRequest) -> Dict[str, Any]:
        """스트리밍 모드 처리"""
        # 스트리밍 STT 프로세서로 요청 전송
        chunk_duration = request.chunk_duration if request.chunk_duration else 5.0
        overlap_duration = request.overlap_duration if request.overlap_duration else 1.0

        streaming_request = {
            "task_id": request.task_id,
            "audio_file_path": request.audio_file_path,
            "language": "ja",
            "chunk_duration": float(chunk_duration),
            "overlap_duration": float(overlap_duration),
            "priority": request.priority
        }

        # Kafka로 스트리밍 요청 전송 (입력 토픽)
        self.kafka_producer.send(
            'streaming_requests',
            key=request.task_id,
            value=streaming_request
        )

        # Redis에 작업 상태 저장
        task_status = {
            "task_id": request.task_id,
            "mode": "streaming",
            "status": "processing",
            "created_at": time.time(),
            "priority": request.priority,
            "max_latency": request.max_latency
        }

        await self.redis_client.setex(
            f"streaming_task:{request.task_id}",
            3600,  # 1시간 TTL
            json.dumps(task_status, ensure_ascii=False)
        )

        return {
            "task_id": request.task_id,
            "mode": "streaming",
            "status": "processing",
            "message": "스트리밍 모드로 처리 중입니다",
            "estimated_first_result": 8,  # 8초 이내 첫 결과
            "estimated_completion": 30    # 30초 이내 완료
        }

    async def get_rollout_status(self) -> Dict[str, Any]:
        """롤아웃 상태 조회"""
        try:
            percentage = await self.feature_flag.get_rollout_percentage()
            updated = await self.redis_client.get("streaming_rollout_updated")

            return {
                "streaming_percentage": percentage,
                "legacy_percentage": 100 - percentage,
                "last_updated": float(updated) if updated else 0,
                "active_connections": len(self.websocket_manager.active_connections),
                "active_tasks": len(self.websocket_manager.task_connections)
            }

        except Exception as e:
            logger.error(f"❌ 롤아웃 상태 조회 실패: {e}")
            return {"error": str(e)}

    async def set_rollout_percentage(self, percentage: int) -> Dict[str, Any]:
        """롤아웃 비율 설정"""
        try:
            success = await self.feature_flag.set_rollout_percentage(percentage)

            if success:
                return {
                    "success": True,
                    "percentage": percentage,
                    "message": f"스트리밍 롤아웃이 {percentage}%로 설정되었습니다"
                }
            else:
                return {
                    "success": False,
                    "message": "롤아웃 비율 설정에 실패했습니다"
                }

        except Exception as e:
            logger.error(f"❌ 롤아웃 비율 설정 실패: {e}")
            return {"success": False, "error": str(e)}

    async def handle_websocket_connection(self, websocket: WebSocket, connection_id: str):
        """WebSocket 연결 처리"""
        try:
            await self.websocket_manager.connect(websocket, connection_id)

            while True:
                try:
                    # 클라이언트 메시지 대기
                    data = await websocket.receive_json()

                    # 작업 바인딩 요청 처리
                    if data.get("type") == "bind_task":
                        task_id = data.get("task_id")
                        if task_id:
                            await self.websocket_manager.bind_task(task_id, connection_id)
                            await websocket.send_json({
                                "type": "bind_success",
                                "task_id": task_id,
                                "connection_id": connection_id
                            })

                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"❌ WebSocket 메시지 처리 오류: {e}")
                    break

        except Exception as e:
            logger.error(f"❌ WebSocket 연결 처리 오류: {e}")
        finally:
            self.websocket_manager.disconnect(connection_id)

    # ===== API Gateway compatibility helpers =====
    async def handle_translation_request(self, request: "StreamingTranslationRequest") -> Dict[str, Any]:
        """Compatibility wrapper matching API route expectation."""
        # Reuse streaming processing path
        return await self.process_streaming_request(request)

    async def get_streaming_status(self, task_id: str) -> Dict[str, Any]:
        """Fetch streaming task status from Redis (fallback defaults)."""
        try:
            raw = await self.redis_client.get(f"streaming_task:{task_id}")
            if not raw:
                # Fallback to coordinator key if present
                raw = await self.redis_client.get(f"stream:{task_id}")
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.warning(f"⚠️ 상태 조회 실패: {e}")
        return {"task_id": task_id, "status": "unknown"}

    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Return lightweight streaming metrics for monitoring."""
        try:
            percentage = await self.feature_flag.get_rollout_percentage()
        except Exception:
            percentage = 0
        return {
            "active_connections": len(self.websocket_manager.active_connections),
            "active_tasks": len(self.websocket_manager.task_connections),
            "rollout_percentage": percentage,
        }

    async def update_rollout_percentage(self, percentage: int) -> Dict[str, Any]:
        """Compatibility wrapper for rollout update."""
        return await self.set_rollout_percentage(percentage)
