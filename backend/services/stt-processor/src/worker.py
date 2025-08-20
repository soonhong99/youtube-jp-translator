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

from .stt import transcribe_audio_file_with_timestamps
from .kafka_config import (
    KAFKA_BOOTSTRAP_SERVERS, 
    STT_REQUEST_TOPIC, 
    STT_RESULT_TOPIC
)
from .gemini_config import get_gemini_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class STTWorker:
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.producer = self._init_producer()
        self.consumer = self._init_consumer()
        self._init_gemini()
        
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
        """Kafka Consumer 초기화"""
        for attempt in range(5):
            try:
                consumer = KafkaConsumer(
                    STT_REQUEST_TOPIC,
                    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                    value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                    group_id='stt_workers',
                    auto_offset_reset='earliest'
                )
                logger.info("Kafka Consumer initialized")
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
    
    def send_update(self, task_id: str, status: str, progress: int = None, 
                   data: Any = None, error: str = None):
        """진행 상황 업데이트 전송"""
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
        
        try:
            self.producer.send(
                STT_RESULT_TOPIC, 
                value=message,
                key=task_id.encode('utf-8')
            )
            self.producer.flush()
            logger.info(f"[{task_id}] Sent update: {status} ({progress}%)")
        except Exception as e:
            logger.error(f"[{task_id}] Failed to send update: {e}")
    
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
    
    async def process_audio(self, task_id: str, wav_path: str, language: str):
        """전체 오디오 처리 (비동기 + 병렬 처리)"""
        logger.info(f"[{task_id}] Processing: {wav_path}")
        self.send_update(task_id, "PROCESSING", 0)
        
        try:
            # 1. 오디오 로드 및 분할
            audio = AudioSegment.from_wav(wav_path)
            duration_ms = len(audio)
            chunk_length_ms = 60000  # 60초
            
            chunks = []
            offsets = []
            for i in range(0, duration_ms, chunk_length_ms):
                chunks.append(audio[i:min(i + chunk_length_ms, duration_ms)])
                offsets.append(i / 1000.0)
            
            self.send_update(task_id, "PROCESSING", 10, 
                           data={"message": f"Split into {len(chunks)} chunks"})
            
            # 2. 병렬 STT 처리
            chunk_dir = Path(f"/tmp/chunks_{task_id}")
            chunk_dir.mkdir(exist_ok=True)
            
            futures = []
            loop = asyncio.get_event_loop()
            
            for i, (chunk, offset) in enumerate(zip(chunks, offsets)):
                chunk_path = chunk_dir / f"chunk_{i}.wav"
                chunk.export(str(chunk_path), format="wav")
                
                # ThreadPoolExecutor를 통한 병렬 처리
                future = loop.run_in_executor(
                    self.executor,
                    self.process_chunk,
                    str(chunk_path),
                    language,
                    offset
                )
                futures.append(future)
            
            # 모든 청크 처리 대기
            all_segments = []
            for i, future in enumerate(asyncio.as_completed(futures)):
                segments = await future
                all_segments.extend(segments)
                progress = 10 + int(80 * (i + 1) / len(futures))
                self.send_update(task_id, "PROCESSING", progress)
            
            # 정렬
            all_segments.sort(key=lambda x: x['start'])
            
            # 3. 일괄 번역
            if all_segments:
                self.send_update(task_id, "TRANSLATING", 90)
                texts = [seg['text'] for seg in all_segments]
                translations = await self.translate_batch(texts)
                
                for seg, trans in zip(all_segments, translations):
                    seg['korean_text'] = trans
            
            # 4. 완료
            self.send_update(task_id, "COMPLETED", 100, data=all_segments)
            
            # 정리
            import shutil
            shutil.rmtree(chunk_dir, ignore_errors=True)
            
        except Exception as e:
            logger.error(f"[{task_id}] Processing failed: {e}")
            self.send_update(task_id, "FAILED", error=str(e))
    
    def run(self):
        """메인 실행 루프"""
        logger.info("STT Worker started")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            for message in self.consumer:
                request = message.value
                task_id = request.get('task_id')
                wav_path = request.get('wav_file_path')
                language = request.get('language', 'ja')
                
                if task_id and wav_path:
                    logger.info(f"Received task: {task_id}")
                    loop.run_until_complete(
                        self.process_audio(task_id, wav_path, language)
                    )
        except KeyboardInterrupt:
            logger.info("Worker interrupted")
        finally:
            self.consumer.close()
            self.producer.close()
            self.executor.shutdown()

if __name__ == "__main__":
    worker = STTWorker(max_workers=4)
    worker.run()