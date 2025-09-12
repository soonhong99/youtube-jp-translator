import os
import json
import logging
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any
import time

from kafka import KafkaConsumer, KafkaProducer
from pydub import AudioSegment
import google.generativeai as genai
import re

from .stt import transcribe_audio_file_with_timestamps

# NLP 라이브러리 import (문장 분절용)
NLP_AVAILABLE = False
BUNKAI_AVAILABLE = False
SPACY_AVAILABLE = False

try:
    import bunkai
    BUNKAI_AVAILABLE = True
    NLP_AVAILABLE = True
    print("bunkai loaded successfully")
except ImportError as e:
    print(f"Warning: bunkai not available - {e}")
except Exception as e:
    print(f"Warning: bunkai error - {e}")

try:
    import spacy
    SPACY_AVAILABLE = True
    print("spacy loaded successfully")
except ImportError as e:
    print(f"Warning: spacy not available - {e}")
except Exception as e:
    print(f"Warning: spacy error - {e}")

if not NLP_AVAILABLE:
    print("Warning: No NLP libraries available. Using basic sentence segmentation.")
from .kafka_config import (
    KAFKA_BOOTSTRAP_SERVERS, 
    STT_REQUEST_TOPIC, 
    STT_RESULT_TOPIC
)

# AI Orchestrator 토픽 추가
AI_PROCESSING_REQUEST_TOPIC = "ai_processing_requests"
from .gemini_config import get_gemini_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# System metrics logger (local adapter)
from .system_logger_adapter import (
    log_kafka_message,
    log_timeline,
    log_performance,
)

class STTWorker:
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.producer = self._init_producer()
        self.consumer = self._init_consumer()
        # 처리 중인 태스크 추적 (중복 방지)
        self.processing_tasks = set()
        # 현재 처리 중인 작업 취소를 위한 이벤트
        self.current_task_cancel_event = asyncio.Event()
        self.current_task_id = None
        self._init_gemini()
        self._init_nlp()
        
    def _init_producer(self) -> KafkaProducer:
        """Kafka Producer 초기화"""
        for attempt in range(5):
            try:
                producer = KafkaProducer(
                    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                    retries=3,
                    acks='all'
                )
                logger.info("Kafka Producer initialized")
                return producer
            except Exception as e:
                logger.error(f"Failed to init producer (attempt {attempt + 1}): {e}")
                time.sleep(5)
        raise RuntimeError("Failed to initialize Kafka Producer")
    
    def _init_consumer(self) -> KafkaConsumer:
        """Kafka Consumer 초기화 - 최신 메시지 우선 처리"""
        for attempt in range(5):
            try:
                consumer = KafkaConsumer(
                    STT_REQUEST_TOPIC,
                    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                    value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                    group_id='stt_workers_priority',  # 새로운 그룹으로 변경
                    auto_offset_reset='latest',  # 최신 메시지부터 처리
                    max_poll_interval_ms=600000,  # 10분으로 증가
                    session_timeout_ms=60000,     # 60초로 증가
                    heartbeat_interval_ms=20000,  # 20초로 증가
                    enable_auto_commit=True,
                    auto_commit_interval_ms=5000
                )
                logger.info("Kafka Consumer initialized with latest-first processing")
                return consumer
            except Exception as e:
                logger.error(f"Failed to init consumer (attempt {attempt + 1}): {e}")
                time.sleep(5)
        raise RuntimeError("Failed to initialize Kafka Consumer")
    
    def _init_gemini(self):
        """Gemini API 초기화"""
        self.gemini_config = get_gemini_config()
        self.gemini_model = self.gemini_config.model_instance
        
        # 모델 정보 로깅
        model_info = self.gemini_config.get_model_info()
        logger.info(f"Worker Gemini configuration: {model_info}")
        
        if not self.gemini_config.is_available():
            logger.warning("Gemini translation model is not available in worker. Translation will be disabled.")
    
    def _init_nlp(self):
        """NLP 라이브러리 초기화 (가벼운 라이브러리 우선)"""
        self.nlp_model = None
        self.sentence_segmenter = None
        
        if BUNKAI_AVAILABLE:
            try:
                # bunkai 문장 분절기 먼저 시도 (가벼움)
                self.sentence_segmenter = bunkai.Bunkai()
                logger.info("Bunkai sentence segmenter initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize bunkai: {e}")
        
        if SPACY_AVAILABLE and not self.sentence_segmenter:
            try:
                # spaCy는 백업으로만 사용
                self.nlp_model = spacy.load("ja_core_news_sm")
                logger.info("spaCy Japanese model loaded as fallback")
            except OSError:
                logger.warning("spaCy Japanese model not found")
        
        if not self.nlp_model and not self.sentence_segmenter:
            logger.warning("No NLP model available, will use basic sentence segmentation")
    

    def send_update(self, task_id: str, status: str, progress: int = None, 
                   data: Any = None, error: str = None, step_detail: str = None, 
                   processing_time: float = None, estimated_remaining: float = None):
        """진행 상황 업데이트 전송 (상세 정보 포함)"""
        message = {
            "task_id": task_id,
            "status": status,
            "timestamp": time.time()
        }
        if progress is not None:
            message["progress"] = max(0, min(100, progress))
        if data is not None:
            message["data"] = data
        if error is not None:
            message["error"] = error
        if step_detail is not None:
            message["step_detail"] = step_detail
        if processing_time is not None:
            message["processing_time"] = processing_time
        if estimated_remaining is not None:
            message["estimated_remaining"] = estimated_remaining
        
        try:
            self.producer.send(
                STT_RESULT_TOPIC, 
                value=message,
                key=task_id.encode('utf-8')
            )
            self.producer.flush()
            detail_msg = f" - {step_detail}" if step_detail else ""
            time_msg = f" ({processing_time:.1f}s)" if processing_time else ""
            remaining_msg = f" ~{estimated_remaining:.0f}s 남음" if estimated_remaining else ""
            logger.info(f"[{task_id}] Sent update: {status} ({progress}%){detail_msg}{time_msg}{remaining_msg}")

            # --- system metrics logging ---
            try:
                log_kafka_message(
                    task_id,
                    topic=STT_RESULT_TOPIC,
                    message=f"{status}",
                    extra={
                        "progress": progress if progress is not None else 0,
                        "step_detail": step_detail or "",
                        "processing_time": processing_time if processing_time is not None else "",
                        "estimated_remaining": estimated_remaining if estimated_remaining is not None else "",
                    },
                )
                # timeline entry for human-readable phase
                if step_detail:
                    log_timeline(
                        task_id,
                        agent="stt-worker",
                        task=step_detail,
                        progress=progress or 0,
                        duration=processing_time if processing_time is not None else None,
                    )
                # performance metric on availability
                if processing_time is not None and status in ("PROCESSING", "STT_COMPLETED", "STT_COMPLETED_SENTENCE_FIRST"):
                    log_performance(task_id, {"stt_processing_time": processing_time})
            except Exception:
                pass
        except Exception as e:
            logger.error(f"[{task_id}] Failed to send update: {e}")
    
    def send_ai_processing_request(self, ai_request: dict):
        """AI Orchestrator로 처리 요청 전송 (취소 확인 포함)"""
        task_id = ai_request.get('task_id')
        
        # 전송 직전 취소 확인
        if self.current_task_cancel_event.is_set():
            logger.info(f"[{task_id}] AI request cancelled before sending")
            return
            
        try:
            self.producer.send(
                AI_PROCESSING_REQUEST_TOPIC,
                value=ai_request,
                key=ai_request["task_id"].encode('utf-8')
            )
            self.producer.flush()
            logger.info(f"AI processing request sent for task: {ai_request['task_id']}")
        except Exception as e:
            logger.error(f"Error sending AI processing request: {e}")
    
    def is_ai_orchestrator_available(self) -> bool:
        """AI Orchestrator 가용성 확인"""
        try:
            # Gemini API 할당량 초과 문제로 일시적으로 fallback 사용
            return False  # fallback 번역 강제 사용
        except:
            return False
    
    def process_chunk(self, chunk_path: str, language: str, offset: float) -> List[Dict]:
        """단일 청크 처리 (동기 함수)"""
        try:
            segments = transcribe_audio_file_with_timestamps(chunk_path, language)
            # 타임스탬프 조정
            for seg in segments:
                seg['start'] = round(seg['start'] + offset, 3)
                seg['end'] = round(seg['end'] + offset, 3)
            return segments
        except Exception as e:
            logger.error(f"Error processing chunk {chunk_path}: {e}")
            return []
    
    async def translate_batch(self, texts: List[str]) -> List[str]:
        """일괄 번역 (비동기)"""
        if not self.gemini_config.is_available() or not texts:
            return ["[번역 불가]"] * len(texts)
        
        separator = "[SEG]"
        combined = f"\n{separator}\n".join(texts)
        
        # 프롬프트 엔지니어링 개선
        prompt = f"""다음은 유튜브에서 추출한 일본어 음성을 텍스트로 변환한 결과입니다. 
        각 문장은 "{separator}"로 구분되어 있습니다.
        매우 자연스러운 한국어 구어체로 번역하되, 원문의 뉘앙스와 감정을 그대로 전달해주세요.
        
        일본어 원문:
        {combined}
        
        한국어 번역:"""
        
        try:
            # 설정된 temperature 사용
            generation_config = self.gemini_config.get_generation_config()
            response = await self.gemini_model.generate_content_async(
                prompt,
                generation_config=generation_config
            )
            
            if response.parts:
                translated = response.text.strip().split(f"{separator}\n")
                if len(translated) == len(texts):
                    logger.info(f"Batch translation successful: {len(texts)} segments translated using {self.gemini_config.model_name}")
                    return translated
                else:
                    logger.warning(f"Translation segment count mismatch: expected {len(texts)}, got {len(translated)}")
        except Exception as e:
            logger.error(f"Translation error with model {self.gemini_config.model_name}: {e}")
        
        return ["[번역 오류]"] * len(texts)
    
    async def process_audio(self, task_id: str, wav_path: str, language: str, request_data: dict = None):
        """전체 오디오 통합 처리 (취소 가능한 우선순위 처리)"""
        logger.info(f"[{task_id}] Starting unified audio processing: {wav_path}")
        start_time = time.time()
        
        # 취소 확인
        if self.current_task_cancel_event.is_set():
            logger.info(f"[{task_id}] Task cancelled before processing started")
            return
        
        # 오디오 파일 정보 수집
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_wav(wav_path)
            duration_seconds = len(audio) / 1000.0
            estimated_processing_time = duration_seconds * 0.3  # 대략적인 처리 시간 추정
            
            self.send_update(task_id, "PROCESSING", 0, 
                           step_detail=f"오디오 분석 완료 ({duration_seconds:.1f}초)", 
                           processing_time=time.time() - start_time,
                           estimated_remaining=estimated_processing_time)
        except Exception as e:
            logger.warning(f"[{task_id}] Failed to analyze audio file: {e}")
            self.send_update(task_id, "PROCESSING", 0, 
                           step_detail="오디오 파일 처리 시작", 
                           processing_time=time.time() - start_time)
        
        # request_data가 None인 경우 기본값 설정
        if request_data is None:
            request_data = {"ai_mode": "standard", "custom_settings": {}}
        
        try:
            # 취소 확인
            if self.current_task_cancel_event.is_set():
                logger.info(f"[{task_id}] Task cancelled during initialization")
                return
                
            # 1. 전체 오디오를 통째로 STT 처리 (단어별 타임스탬프 포함)
            self.send_update(task_id, "PROCESSING", 10, 
                           step_detail="Faster-Whisper STT 모델 로딩 중",
                           processing_time=time.time() - start_time,
                           data={"message": "Starting full audio STT processing"})
            
            logger.info(f"[{task_id}] Processing entire audio file with faster-whisper")
            
            # 취소 확인
            if self.current_task_cancel_event.is_set():
                logger.info(f"[{task_id}] Task cancelled before STT processing")
                return
            
            # ThreadPoolExecutor를 통한 STT 처리 (단어 타임스탬프 포함)
            loop = asyncio.get_event_loop()
            stt_result = await loop.run_in_executor(
                self.executor,
                self.process_full_audio_with_timestamps,
                wav_path,
                language,
                task_id  # 취소 확인을 위해 task_id 전달
            )
            
            # 취소 확인
            if self.current_task_cancel_event.is_set():
                logger.info(f"[{task_id}] Task cancelled after STT processing")
                return
                
            if not stt_result or not stt_result.get('full_text'):
                raise Exception("STT processing failed or returned empty result")
            
            full_text = stt_result['full_text']
            word_timestamps = stt_result.get('word_timestamps', [])
            
            word_count = len(full_text.split()) if full_text else 0
            self.send_update(task_id, "PROCESSING", 40, 
                           step_detail=f"STT 완료 ({len(full_text)}자, {word_count}단어)",
                           processing_time=time.time() - start_time,
                           data={"message": f"STT completed. Text length: {len(full_text)}"})
            
            # 취소 확인
            if self.current_task_cancel_event.is_set():
                logger.info(f"[{task_id}] Task cancelled before AI processing")
                return
                
            self.send_update(task_id, "STT_COMPLETED", 70)
            
            # 4. AI Orchestrator로 새로운 sentence-first 워크플로우 요청
            logger.info(f"[{task_id}] Preparing sentence-first workflow request")
            
            # AI 처리 요청 데이터 준비 (원본 텍스트와 타임스탬프 포함)
            ai_request = {
                "task_id": task_id,
                "workflow_type": "sentence_first",  # 새로운 워크플로우 지정
                "raw_text": full_text,  # 전체 원본 일본어 텍스트
                "word_timestamps": word_timestamps,  # 단어별 타임스탬프
                "mode": request_data.get("ai_mode", "standard"),
                "custom_settings": request_data.get("custom_settings", {}),
                "language": language,
                "stt_metadata": {
                    "language_detected": stt_result.get('language', language),
                    "language_probability": stt_result.get('language_probability', 0.0),
                    "processing_method": "unified_stt_sentence_first"
                }
            }
            
            # 마지막 취소 확인 - AI 요청 전
            if self.current_task_cancel_event.is_set():
                logger.info(f"[{task_id}] Task cancelled before sending AI request")
                return
            
            logger.info(f"[{task_id}] Sending sentence-first workflow request to AI Orchestrator...")
            # AI Orchestrator로 전송
            self.send_ai_processing_request(ai_request)
            logger.info(f"[{task_id}] Sentence-first workflow request sent - text length: {len(full_text)}")
            
            # STT 완료 상태 전송 (AI Orchestrator가 나머지 처리)
            self.send_update(task_id, "STT_COMPLETED_SENTENCE_FIRST", 70, 
                           data={
                               "message": "STT 완료 - AI 문장 분할 및 번역 시작",
                               "text_length": len(full_text),
                               "word_count": len(word_timestamps),
                               "estimated_segments": len(full_text.split('。')) + len(full_text.split('！')) + len(full_text.split('？'))
                           })
            
        except Exception as e:
            logger.error(f"[{task_id}] Unified processing failed: {e}")
            self.send_update(task_id, "FAILED", 
                           step_detail=f"처리 실패: {str(e)[:100]}...", 
                           processing_time=time.time() - start_time,
                           error=str(e))
    
    def process_full_audio_with_timestamps(self, wav_path: str, language: str, task_id: str = None) -> Dict[str, Any]:
        """전체 오디오를 단어 타임스탬프와 함께 STT 처리"""
        try:
            # faster-whisper를 사용해 전체 오디오 처리 (단어 타임스탬프 포함)
            from faster_whisper import WhisperModel
            
            # 모델 로드 (이미 초기화되어 있다면 재사용)
            model_size = "base"  # 환경에 따라 조정 가능
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            
            # 전체 오디오 transcribe (단어 타임스탬프 포함)
            segments, info = model.transcribe(
                wav_path, 
                language=language,
                word_timestamps=True,  # 단어별 타임스탬프 활성화
                vad_filter=True,       # Voice Activity Detection
                beam_size=5            # 품질 향상
            )
            
            full_text = ""
            word_timestamps = []
            
            # 결과 수집
            for segment in segments:
                # 취소 확인 (동기 함수에서의 비동기 이벤트 확인)
                if task_id and self.current_task_cancel_event.is_set():
                    logger.info(f"[{task_id}] STT processing cancelled during segment processing")
                    return {}
                    
                full_text += segment.text + " "
                
                # 단어별 타임스탬프 수집
                if hasattr(segment, 'words') and segment.words:
                    for word in segment.words:
                        word_timestamps.append({
                            'word': word.word,
                            'start': word.start,
                            'end': word.end,
                            'probability': getattr(word, 'probability', 1.0)
                        })
            
            return {
                'full_text': full_text.strip(),
                'word_timestamps': word_timestamps,
                'language': info.language,
                'language_probability': info.language_probability
            }
            
        except Exception as e:
            logger.error(f"Full audio STT processing failed: {e}")
            return {}
    
    def run(self):
        """메인 실행 루프 - 최신 요청 우선 처리"""
        logger.info("STT Worker started with priority processing")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            for message in self.consumer:
                request = message.value
                task_id = request.get('task_id')
                wav_path = request.get('wav_file_path')
                language = request.get('language', 'ja')
                
                if task_id and wav_path:
                    # 기존 작업 취소 및 새로운 작업 시작
                    if self.current_task_id and self.current_task_id != task_id:
                        logger.info(f"Cancelling current task {self.current_task_id} for new task {task_id}")
                        self.current_task_cancel_event.set()
                        
                        # 이전 작업에 취소 신호 보내기
                        self._send_cancellation_message(self.current_task_id)
                        
                        # 짧은 대기 후 취소 이벤트 리셋
                        time.sleep(1)
                        self.current_task_cancel_event.clear()
                    
                    # 중복 처리 방지
                    if task_id in self.processing_tasks:
                        logger.warning(f"Task {task_id} is already being processed, skipping")
                        continue
                    
                    logger.info(f"Starting new priority task: {task_id}")
                    self.current_task_id = task_id
                    self.processing_tasks.add(task_id)
                    
                    try:
                        loop.run_until_complete(
                            self.process_audio(task_id, wav_path, language, request)
                        )
                    finally:
                        # 처리 완료 후 태스크 제거
                        self.processing_tasks.discard(task_id)
                        if self.current_task_id == task_id:
                            self.current_task_id = None
        except KeyboardInterrupt:
            logger.info("Worker interrupted")
        finally:
            self.consumer.close()
            self.producer.close()
            self.executor.shutdown()
    
    def _send_cancellation_message(self, task_id: str):
        """취소된 작업에 취소 메시지 전송"""
        try:
            result = {
                'task_id': task_id,
                'status': 'CANCELLED',
                'progress': 0,
                'data': None,
                'error': 'Task cancelled due to new request priority'
            }
            
            self.producer.send(STT_RESULT_TOPIC, value=result)
            self.producer.flush()
            logger.info(f"Sent cancellation message for task: {task_id}")
        except Exception as e:
            logger.error(f"Failed to send cancellation message: {e}")

if __name__ == "__main__":
    worker = STTWorker(max_workers=4)
    worker.run()
