"""
Streaming STT Worker
실시간 음성 인식을 위한 Kafka 기반 워커
"""

import asyncio
import json
import logging
import time
import tempfile
import io
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import soundfile as sf

from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import KafkaError
import redis.asyncio as redis
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

@dataclass
class STTChunk:
    """STT 청크 데이터 구조"""
    chunk_id: str
    task_id: str
    start_time: float
    end_time: float
    text: str
    confidence: float
    is_final: bool = False
    speaker_change: bool = False
    language: str = "ja"

@dataclass
class StreamingProgress:
    """스트리밍 진행 상황"""
    task_id: str
    total_chunks: int
    processed_chunks: int
    current_chunk: int
    progress_percent: float
    estimated_remaining: float
    status: str
    error_message: Optional[str] = None

class StreamingSTTWorker:
    """스트리밍 STT 워커 클래스"""

    def __init__(self, whisper_pool, audio_chunker, sentence_detector, config):
        self.whisper_pool = whisper_pool
        self.audio_chunker = audio_chunker
        self.sentence_detector = sentence_detector
        self.config = config

        # Kafka 설정
        self.producer = None
        self.consumer = None

        # Redis 설정
        self.redis_client = None

        # 작업 상태 관리
        self.active_tasks: Dict[str, Dict] = {}
        self.task_stats: Dict[str, Dict] = {}

        # 워커 상태
        self.is_running = False
        self.worker_task = None

        # 메트릭
        self.metrics = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "active_tasks": 0,
            "avg_processing_time": 0.0,
            "total_chunks_processed": 0
        }

    async def start(self):
        """워커 시작"""
        try:
            # Kafka 프로듀서 초기화
            self.producer = KafkaProducer(
                bootstrap_servers=self.config.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda x: json.dumps(x, ensure_ascii=False).encode('utf-8'),
                key_serializer=lambda x: x.encode('utf-8') if x else None,
                acks='all',
                retries=3,
                batch_size=16384,
                linger_ms=10
            )

            # Redis 클라이언트 초기화
            self.redis_client = redis.Redis(
                host=self.config.REDIS_HOST,
                port=self.config.REDIS_PORT,
                db=self.config.REDIS_DB_STT,
                decode_responses=True
            )

            # 연결 테스트
            await self.redis_client.ping()

            self.is_running = True
            logger.info("✅ 스트리밍 STT 워커 시작 완료")

        except Exception as e:
            logger.error(f"❌ 워커 시작 실패: {e}")
            raise

    async def stop(self):
        """워커 종료"""
        self.is_running = False

        if self.worker_task:
            self.worker_task.cancel()

        if self.producer:
            self.producer.close()

        if self.redis_client:
            await self.redis_client.close()

        logger.info("✅ 스트리밍 STT 워커 종료 완료")

    async def process_streaming_stt(
        self,
        task_id: str,
        audio_file_path: str,
        language: str = "ja",
        chunk_duration: float = 5.0,
        overlap_duration: float = 1.0,
        priority: int = 1
    ):
        """스트리밍 STT 처리 메인 함수"""
        start_time = time.time()

        try:
            logger.info(f"🎵 스트리밍 STT 처리 시작: {task_id}")

            # 작업 상태 초기화
            self.active_tasks[task_id] = {
                "status": "processing",
                "start_time": start_time,
                "progress": 0.0,
                "total_chunks": 0,
                "processed_chunks": 0
            }

            # 오디오 청크 생성 (메모리 모드 기본 활성화)
            chunks = await self.audio_chunker.create_chunks(
                audio_file_path,
                chunk_duration,
                overlap_duration,
                memory_mode=True
            )

            total_chunks = len(chunks)
            self.active_tasks[task_id]["total_chunks"] = total_chunks

            logger.info(f"📊 총 {total_chunks}개 청크 생성")

            # 진행 상황 업데이트
            await self._update_progress(task_id, 0, total_chunks, "chunking_complete")

            # 병렬 처리 정보 추가
            self.active_tasks[task_id]["processing_mode"] = "parallel"
            self.active_tasks[task_id]["whisper_models"] = self.whisper_pool.pool_size
            self.active_tasks[task_id]["memory_mode"] = True

            # 병렬 STT 처리 시작
            stt_results = await self._process_chunks_parallel(
                chunks, task_id, language, priority
            )

            # 문장 단위로 재구성
            sentences = await self.sentence_detector.reconstruct_sentences(stt_results)

            # 최종 결과 전송
            await self._send_final_result(task_id, sentences)

            # 작업 완료 처리
            processing_time = time.time() - start_time
            await self._complete_task(task_id, processing_time, len(stt_results))

            logger.info(f"✅ 스트리밍 STT 완료: {task_id} ({processing_time:.2f}초)")

        except Exception as e:
            logger.error(f"❌ 스트리밍 STT 처리 실패 {task_id}: {e}")
            await self._fail_task(task_id, str(e))
        finally:
            # 메모리 기반 청킹 정리
            await self.audio_chunker.cleanup_chunks(chunks)

    async def _process_chunks_parallel(
        self,
        chunks: List[Dict],
        task_id: str,
        language: str,
        priority: int = 1
    ) -> List[STTChunk]:
        """병렬 STT 처리 - Phase 1 핵심 최적화"""
        if not chunks:
            return []

        total_chunks = len(chunks)
        logger.info(f"🔄 병렬 STT 처리 시작: {total_chunks}개 청크, {self.whisper_pool.pool_size}개 모델")

        # 배치 크기: Whisper 모델 풀 크기와 매칭
        batch_size = min(self.whisper_pool.pool_size, len(chunks))

        # 청크를 배치로 분할
        chunk_batches = [
            chunks[i:i + batch_size]
            for i in range(0, len(chunks), batch_size)
        ]

        stt_results = []
        processed_count = 0

        # 배치별 병렬 처리
        for batch_idx, batch in enumerate(chunk_batches):
            logger.debug(f"📦 배치 {batch_idx + 1}/{len(chunk_batches)} 처리 중: {len(batch)}개 청크")

            # 배치 내 병렬 처리 태스크 생성
            batch_tasks = [
                self._process_chunk_optimized(chunk, task_id, language, chunk_idx)
                for chunk_idx, chunk in enumerate(batch, start=processed_count)
            ]

            try:
                # 병렬 실행 + 타임아웃 (청크당 10초)
                batch_timeout = len(batch) * 10
                batch_results = await asyncio.wait_for(
                    asyncio.gather(*batch_tasks, return_exceptions=True),
                    timeout=batch_timeout
                )

                # 유효 결과만 수집 + 상세 오류 분석
                valid_results = []
                failed_chunks = []

                for idx, result in enumerate(batch_results):
                    if isinstance(result, Exception):
                        chunk_idx = processed_count + idx
                        error_info = {
                            "batch_idx": batch_idx,
                            "chunk_idx": chunk_idx,
                            "local_idx": idx,
                            "error": str(result),
                            "error_type": type(result).__name__
                        }
                        failed_chunks.append(error_info)
                        logger.error(f"❌ 배치 {batch_idx}, 청크 {chunk_idx} 처리 실패: {result}")
                    elif result:
                        valid_results.append(result)
                        # 실시간 청크 결과 전송
                        try:
                            await self._send_chunk_result(result)
                        except Exception as send_error:
                            logger.warning(f"⚠️ 청크 결과 전송 실패: {send_error}")

                # 실패한 청크에 대한 복구 시도 (선택적)
                if failed_chunks and len(failed_chunks) < len(batch) * 0.5:  # 50% 미만 실패시만
                    logger.info(f"🔄 배치 {batch_idx + 1}: {len(failed_chunks)}개 청크 복구 시도")
                    recovered_results = await self._retry_failed_chunks(
                        failed_chunks, batch, task_id, language
                    )
                    valid_results.extend(recovered_results)

                stt_results.extend(valid_results)
                processed_count += len(batch)

                # 배치 성공률 계산
                success_rate = len(valid_results) / len(batch) * 100

                # 실시간 진행 상황 업데이트
                await self._update_batch_progress(
                    task_id, processed_count, total_chunks, batch_idx + 1, len(chunk_batches),
                    success_rate=success_rate, failed_count=len(failed_chunks)
                )

                logger.debug(f"✅ 배치 {batch_idx + 1} 완료: {len(valid_results)}/{len(batch)}개 성공 ({success_rate:.1f}%)")

            except asyncio.TimeoutError:
                logger.error(f"⏰ 배치 {batch_idx + 1} 타임아웃 ({batch_timeout}초)")
                # 타임아웃 시에도 진행 상황 업데이트
                processed_count += len(batch)
                await self._update_batch_progress(
                    task_id, processed_count, total_chunks, batch_idx + 1, len(chunk_batches),
                    success_rate=0.0, failed_count=len(batch)
                )
            except Exception as e:
                logger.error(f"❌ 배치 {batch_idx + 1} 처리 실패: {e}")
                # 예외 발생시에도 진행 상황 업데이트
                processed_count += len(batch)
                await self._update_batch_progress(
                    task_id, processed_count, total_chunks, batch_idx + 1, len(chunk_batches),
                    success_rate=0.0, failed_count=len(batch)
                )

        logger.info(f"✅ 병렬 STT 처리 완료: {len(stt_results)}/{total_chunks}개 청크 성공")
        return stt_results

    async def _process_chunk_optimized(
        self,
        chunk_info: Dict,
        task_id: str,
        language: str,
        chunk_index: int
    ) -> Optional[STTChunk]:
        """최적화된 청크 처리 (메모리 기반 + 성능 튜닝)"""
        model = None
        try:
            chunk_id = f"{task_id}_chunk_{chunk_index}"

            # Whisper 모델 풀에서 모델 획득
            model = await self.whisper_pool.get_model()

            # 메모리 기반 vs 파일 기반 처리 분기
            if chunk_info.get("memory_mode", False):
                result = await self._transcribe_from_memory(
                    model, chunk_info, chunk_id, task_id, language
                )
            else:
                result = await self._transcribe_from_file(
                    model, chunk_info, chunk_id, task_id, language
                )

            # 메트릭 업데이트
            self.metrics["total_chunks_processed"] += 1
            return result

        except Exception as e:
            logger.error(f"❌ 청크 {chunk_index} 최적화 처리 실패: {e}")
            return None
        finally:
            if model:
                await self.whisper_pool.return_model(model)

    async def _transcribe_from_memory(
        self,
        model,
        chunk_info: Dict,
        chunk_id: str,
        task_id: str,
        language: str
    ) -> Optional[STTChunk]:
        """메모리 기반 STT 처리 (디스크 I/O 제거)"""
        try:
            # ndarray를 직접 입력하고, 동기 호출을 스레드로 오프로딩하여 이벤트 루프 블로킹 제거
            audio_array = np.asarray(chunk_info["audio_data"], dtype=np.float32)

            segments, info = await asyncio.to_thread(
                model.transcribe,
                audio_array,
                language=language,
                beam_size=3,        # 5→3 (속도 우선)
                best_of=3,          # 5→3 (속도 우선)
                temperature=0.1,    # 0.0→0.1 (약간의 무작위성 허용)
                condition_on_previous_text=False,  # 청크간 독립성 확보
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,  # 1000→500ms (덜 보수적)
                    speech_pad_ms=30
                )
            )

            return self._extract_chunk_result(segments, info, chunk_info, chunk_id, task_id, language)

        except Exception as e:
            logger.error(f"❌ 메모리 기반 STT 처리 실패: {e}")
            return None

    async def _transcribe_from_file(
        self,
        model,
        chunk_info: Dict,
        chunk_id: str,
        task_id: str,
        language: str
    ) -> Optional[STTChunk]:
        """파일 기반 STT 처리 (기존 방식, 호환성 유지)"""
        try:
            # 동기 transcribe 호출을 스레드로 오프로딩하여 이벤트 루프 블로킹 방지
            segments, info = await asyncio.to_thread(
                model.transcribe,
                chunk_info["file_path"],
                language=language,
                beam_size=3,        # 5→3 (속도 우선)
                best_of=3,          # 5→3 (속도 우선)
                temperature=0.1,    # 0.0→0.1 (약간의 무작위성)
                condition_on_previous_text=False,  # 청크간 독립성
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,  # 1000→500ms
                    speech_pad_ms=30
                )
            )

            return self._extract_chunk_result(segments, info, chunk_info, chunk_id, task_id, language)

        except Exception as e:
            logger.error(f"❌ 파일 기반 STT 처리 실패: {e}")
            return None

    def _extract_chunk_result(
        self,
        segments,
        info,
        chunk_info: Dict,
        chunk_id: str,
        task_id: str,
        language: str
    ) -> Optional[STTChunk]:
        """STT 결과에서 청크 데이터 추출"""
        try:
            # 세그먼트 결합
            text_parts = []
            total_confidence = 0.0
            segment_count = 0

            for segment in segments:
                text_parts.append(segment.text.strip())
                total_confidence += segment.avg_logprob
                segment_count += 1

            if not text_parts:
                return None

            text = " ".join(text_parts)

            # 개선된 반복 억제 후처리
            text = self._apply_repetition_filter(text)

            confidence = total_confidence / segment_count if segment_count > 0 else 0.0

            # 화자 변화 감지 (간단한 버전)
            speaker_change = chunk_info.get("chunk_index", 0) == 0

            return STTChunk(
                chunk_id=chunk_id,
                task_id=task_id,
                start_time=chunk_info["start_time"],
                end_time=chunk_info["end_time"],
                text=text,
                confidence=confidence,
                is_final=False,
                speaker_change=speaker_change,
                language=language
            )

        except Exception as e:
            logger.error(f"❌ 청크 결과 추출 실패: {e}")
            return None

    def _apply_repetition_filter(self, text: str) -> str:
        """개선된 반복 억제 필터 (일본어 특화)"""
        try:
            import re

            # 일본어 특화 반복 패턴 제거
            patterns = [
                # 같은 단어의 과도한 반복 (2~6자)
                (r"(\S{2,6})\s*\1{2,}", r"\1 \1"),
                # 조사나 어미의 반복
                (r"([은는이가을를에서와과]|です|ます)\s*\1+", r"\1"),
                # 감탄사 반복
                (r"(あー|えー|そう|はい)\s*\1{2,}", r"\1")
            ]

            filtered_text = text
            for pattern, replacement in patterns:
                filtered_text = re.sub(pattern, replacement, filtered_text)

            return filtered_text.strip()

        except Exception:
            return text

    

    async def _process_chunk(
        self,
        model,
        chunk_info: Dict,
        task_id: str,
        chunk_index: int,
        language: str
    ) -> Optional[STTChunk]:
        """개별 청크 STT 처리"""
        try:
            chunk_id = f"{task_id}_chunk_{chunk_index}"

            # Whisper로 STT 처리
            segments, info = model.transcribe(
                chunk_info["file_path"],
                language=language,
                beam_size=5,
                best_of=5,
                temperature=0.0,
                condition_on_previous_text=True,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=1000)
            )

            # 세그먼트 결합
            text_parts = []
            total_confidence = 0.0
            segment_count = 0

            for segment in segments:
                text_parts.append(segment.text.strip())
                total_confidence += segment.avg_logprob
                segment_count += 1

            if not text_parts:
                return None

            text = " ".join(text_parts)
            # 간단한 반복 억제 후처리 (같은 구절의 과도한 연속 반복 제거)
            try:
                import re
                # 2~6자 구간의 과도 반복을 2회로 축소
                for n in range(6, 1, -1):
                    pattern = re.compile(rf"((.{{1,{n}}}))\s*\1{3,}")
                    while True:
                        new_text = pattern.sub(r"\1 \1", text)
                        if new_text == text:
                            break
                        text = new_text
            except Exception:
                pass
            confidence = total_confidence / segment_count if segment_count > 0 else 0.0

            # 화자 변화 감지 (간단한 버전)
            speaker_change = chunk_index == 0 or await self._detect_speaker_change(
                text, chunk_index
            )

            return self._extract_chunk_result(segments, info, chunk_info, chunk_id, task_id, language)

        except Exception as e:
            logger.error(f"❌ 청크 처리 오류: {e}")
            return None

    async def _detect_speaker_change(self, text: str, chunk_index: int) -> bool:
        """화자 변화 감지 (간단한 구현)"""
        # 실제로는 더 정교한 화자 인식 알고리즘 필요
        # 여기서는 간단한 휴리스틱 사용
        return len(text.strip()) < 10 and chunk_index % 10 == 0

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _send_chunk_result(self, chunk: STTChunk):
        """실시간 청크 결과 전송"""
        try:
            message = {
                "type": "stt_chunk",
                "task_id": chunk.task_id,
                "data": asdict(chunk),
                "timestamp": time.time()
            }

            # Kafka로 전송
            self.producer.send(
                self.config.KAFKA_TOPIC_STT_CHUNKS,
                key=chunk.task_id,
                value=message
            )

            # Redis에 캐싱
            cache_key = f"stt_chunk:{chunk.task_id}:{chunk.chunk_id}"
            await self.redis_client.setex(
                cache_key,
                self.config.REDIS_TTL_STT_CHUNKS,
                json.dumps(message, ensure_ascii=False)
            )

        except Exception as e:
            logger.error(f"❌ 청크 결과 전송 실패: {e}")
            raise

    async def _send_final_result(self, task_id: str, sentences: List[Dict]):
        """최종 결과 전송"""
        try:
            message = {
                "type": "stt_complete",
                "task_id": task_id,
                "sentences": sentences,
                "timestamp": time.time(),
                "total_segments": len(sentences)
            }

            # Kafka로 전송
            self.producer.send(
                self.config.KAFKA_TOPIC_STT_RESULTS,
                key=task_id,
                value=message
            )

            # Redis에 최종 결과 저장
            result_key = f"stt_result:{task_id}"
            await self.redis_client.setex(
                result_key,
                self.config.REDIS_TTL_STT_RESULTS,
                json.dumps(message, ensure_ascii=False)
            )

            logger.info(f"📤 최종 STT 결과 전송: {task_id} ({len(sentences)}개 문장)")

        except Exception as e:
            logger.error(f"❌ 최종 결과 전송 실패: {e}")

    async def _update_progress(
        self,
        task_id: str,
        processed: int,
        total: int,
        status: str
    ):
        """진행 상황 업데이트"""
        try:
            progress = StreamingProgress(
                task_id=task_id,
                total_chunks=total,
                processed_chunks=processed,
                current_chunk=processed,
                progress_percent=(processed / total) * 100 if total > 0 else 0,
                estimated_remaining=0.0,  # 추후 구현
                status=status
            )

            # Redis에 진행 상황 저장
            progress_key = f"stt_progress:{task_id}"
            await self.redis_client.setex(
                progress_key,
                self.config.REDIS_TTL_PROGRESS,
                json.dumps(asdict(progress), ensure_ascii=False)
            )

            # Kafka로 진행 상황 전송
            message = {
                "type": "stt_progress",
                "data": asdict(progress),
                "timestamp": time.time()
            }

            self.producer.send(
                self.config.KAFKA_TOPIC_STREAMING_CONTROL,
                key=task_id,
                value=message
            )

        except Exception as e:
            logger.error(f"❌ 진행 상황 업데이트 실패: {e}")

    async def _complete_task(self, task_id: str, processing_time: float, chunk_count: int):
        """작업 완료 처리"""
        if task_id in self.active_tasks:
            self.active_tasks[task_id]["status"] = "completed"
            self.active_tasks[task_id]["end_time"] = time.time()
            self.active_tasks[task_id]["processing_time"] = processing_time

        # 메트릭 업데이트
        self.metrics["completed_tasks"] += 1
        self.metrics["active_tasks"] = len(self.active_tasks)

        # 평균 처리 시간 업데이트
        total_completed = self.metrics["completed_tasks"]
        current_avg = self.metrics["avg_processing_time"]
        self.metrics["avg_processing_time"] = (
            (current_avg * (total_completed - 1) + processing_time) / total_completed
        )

    async def _fail_task(self, task_id: str, error_message: str):
        """작업 실패 처리"""
        if task_id in self.active_tasks:
            self.active_tasks[task_id]["status"] = "failed"
            self.active_tasks[task_id]["error"] = error_message

        self.metrics["failed_tasks"] += 1
        self.metrics["active_tasks"] = len(self.active_tasks)

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        """작업 상태 조회"""
        if task_id in self.active_tasks:
            return self.active_tasks[task_id]

        # Redis에서 조회
        try:
            progress_key = f"stt_progress:{task_id}"
            progress_data = await self.redis_client.get(progress_key)
            if progress_data:
                return json.loads(progress_data)
        except Exception as e:
            logger.error(f"❌ 작업 상태 조회 실패: {e}")

        return None

    async def get_status(self) -> Dict[str, Any]:
        """워커 상태 조회"""
        return {
            "is_running": self.is_running,
            "active_tasks": len(self.active_tasks),
            "total_tasks": self.metrics["total_tasks"],
            "completed_tasks": self.metrics["completed_tasks"],
            "failed_tasks": self.metrics["failed_tasks"]
        }

    async def get_metrics(self) -> Dict[str, Any]:
        """성능 메트릭 조회"""
        return self.metrics.copy()

    async def cancel_task(self, task_id: str) -> bool:
        """작업 취소"""
        if task_id in self.active_tasks:
            self.active_tasks[task_id]["status"] = "cancelled"
            return True
        return False

    # ===== Phase 1 병렬 처리 최적화 메서드들 =====

    async def _retry_failed_chunks(
        self,
        failed_chunks: List[Dict],
        original_batch: List[Dict],
        task_id: str,
        language: str,
        max_retries: int = 1
    ) -> List[STTChunk]:
        """실패한 청크에 대한 복구 시도"""
        recovered_results = []

        for failure_info in failed_chunks:
            chunk_idx = failure_info.get("chunk_idx")
            batch_idx = failure_info.get("batch_idx")
            local_idx = failure_info.get("local_idx")

            try:
                # 배치에서 해당 청크 직접 찾기 (모듈로 연산 제거)
                if local_idx is not None and 0 <= local_idx < len(original_batch):
                    chunk = original_batch[local_idx]

                    logger.debug(f"🔄 청크 {chunk_idx} (배치 {batch_idx}, 로컬 {local_idx}) 복구 시도 중...")

                    # 단순 재시도 (더 관대한 파라미터)
                    result = await self._process_chunk_with_fallback(
                        chunk, task_id, language, chunk_idx
                    )

                    if result:
                        recovered_results.append(result)
                        logger.debug(f"✅ 청크 {chunk_idx} 복구 성공")

            except Exception as e:
                logger.warning(f"⚠️ 청크 {chunk_idx} 복구 실패: {e}")

        logger.info(f"🔄 복구 결과: {len(recovered_results)}/{len(failed_chunks)}개 청크 복구됨")
        return recovered_results

    async def _process_chunk_with_fallback(
        self,
        chunk_info: Dict,
        task_id: str,
        language: str,
        chunk_index: int
    ) -> Optional[STTChunk]:
        """폴백 옵션이 있는 청크 처리"""
        model = None
        try:
            chunk_id = f"{task_id}_chunk_{chunk_index}_retry"

            # Whisper 모델 풀에서 모델 획득
            model = await self.whisper_pool.get_model()

            # 더 관대한 파라미터로 STT 처리 (오프로딩)
            if chunk_info.get("memory_mode", False):
                audio_array = np.asarray(chunk_info["audio_data"], dtype=np.float32)

                segments, info = await asyncio.to_thread(
                    model.transcribe,
                    audio_array,
                    language=language,
                    beam_size=1,        # 최소 beam_size
                    best_of=1,          # 최소 best_of
                    temperature=0.3,    # 더 높은 temperature
                    condition_on_previous_text=False,
                    vad_filter=False,   # VAD 비활성화
                )
            else:
                segments, info = await asyncio.to_thread(
                    model.transcribe,
                    chunk_info["file_path"],
                    language=language,
                    beam_size=1,
                    best_of=1,
                    temperature=0.3,
                    condition_on_previous_text=False,
                    vad_filter=False,
                )

            return self._extract_chunk_result(segments, info, chunk_info, chunk_id, task_id, language)

        except Exception as e:
            logger.error(f"❌ 폴백 청크 처리 실패: {e}")
            return None
        finally:
            if model:
                await self.whisper_pool.return_model(model)

    async def _update_batch_progress(
        self,
        task_id: str,
        processed: int,
        total: int,
        current_batch: int,
        total_batches: int,
        success_rate: float = 100.0,
        failed_count: int = 0
    ):
        """배치 기반 진행 상황 업데이트 (성공률 포함)"""
        try:
            # 기존 진행 상황 업데이트에 배치 정보 추가
            if task_id in self.active_tasks:
                self.active_tasks[task_id]["processed_chunks"] = processed
                self.active_tasks[task_id]["progress"] = (processed / total) * 100
                self.active_tasks[task_id]["current_batch"] = current_batch
                self.active_tasks[task_id]["total_batches"] = total_batches
                self.active_tasks[task_id]["success_rate"] = success_rate
                self.active_tasks[task_id]["failed_chunks"] = failed_count

            await self._update_progress(
                task_id, processed, total,
                f"parallel_processing_batch_{current_batch}_{total_batches}_success_{success_rate:.1f}%"
            )

        except Exception as e:
            logger.error(f"❌ 배치 진행 상황 업데이트 실패: {e}")
