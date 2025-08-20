"""
AI Orchestrator Kafka Worker
STT 결과를 받아 AI 에이전트들을 통해 처리하고 결과를 반환
"""
import json
import logging
import asyncio
import time
from typing import Dict, Any
from kafka import KafkaConsumer, KafkaProducer

from .config import (
    KAFKA_BOOTSTRAP_SERVERS,
    AI_PROCESSING_REQUEST_TOPIC, 
    AI_PROCESSING_RESULT_TOPIC,
    LOG_LEVEL
)
from .agents.translator import TranslatorAgent
from .chains.master_chain import MasterChain, ProcessingMode

# 로깅 설정
logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper()))
logger = logging.getLogger(__name__)

class AIOrchestrationWorker:
    """AI 오케스트레이션 워커"""
    
    def __init__(self):
        self.producer = None
        self.consumer = None
        self.master_chain = None
        self.running = False
        
    def _init_kafka_producer(self) -> bool:
        """Kafka Producer 초기화"""
        for attempt in range(5):
            try:
                self.producer = KafkaProducer(
                    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                    retries=3,
                    acks='all'
                )
                logger.info("Kafka Producer initialized successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to init producer (attempt {attempt + 1}): {e}")
                time.sleep(5)
        return False
        
    def _init_kafka_consumer(self) -> bool:
        """Kafka Consumer 초기화"""
        for attempt in range(5):
            try:
                self.consumer = KafkaConsumer(
                    AI_PROCESSING_REQUEST_TOPIC,
                    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                    value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                    group_id='ai_orchestrator_workers',
                    auto_offset_reset='earliest'
                )
                logger.info("Kafka Consumer initialized successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to init consumer (attempt {attempt + 1}): {e}")
                time.sleep(5)
        return False
    
    def _init_master_chain(self) -> bool:
        """마스터 체인 초기화"""
        try:
            # 마스터 체인 초기화 (모든 에이전트와 체인 포함)
            self.master_chain = MasterChain()
            
            if self.master_chain.is_available():
                logger.info("Master chain initialized successfully")
                return True
            else:
                logger.error("Master chain initialization failed")
                return False
                
        except Exception as e:
            logger.error(f"Failed to initialize master chain: {e}")
            return False
    
    def send_result(self, task_id: str, status: str, data: Any = None, error: str = None):
        """처리 결과를 Kafka로 전송"""
        message = {
            "task_id": task_id,
            "status": status,
            "timestamp": time.time(),
            "service": "ai-orchestrator"
        }
        
        if data is not None:
            message["data"] = data
        if error is not None:
            message["error"] = error
            
        try:
            self.producer.send(
                AI_PROCESSING_RESULT_TOPIC,
                value=message,
                key=task_id.encode('utf-8')
            )
            self.producer.flush()
            logger.info(f"[{task_id}] Result sent: {status}")
        except Exception as e:
            logger.error(f"[{task_id}] Failed to send result: {e}")
    
    async def process_translation_request(self, request_data: Dict[str, Any]) -> None:
        """번역 요청 처리 (마스터 체인 사용)"""
        task_id = request_data.get('task_id')
        segments = request_data.get('segments', [])
        request_type = request_data.get('type', 'translation')
        options = request_data.get('options', {})
        
        if not task_id:
            logger.error("Received request without task_id")
            return
            
        logger.info(f"[{task_id}] Processing {request_type} request for {len(segments)} segments")
        
        try:
            # 진행 상황 알림
            self.send_result(task_id, "AI_PROCESSING_STARTED")
            
            # 처리 모드 결정
            if request_type == 'translation':
                # 기본 번역 요청은 standard 모드
                processing_mode = options.get('mode', 'standard')
            else:
                # 기타 요청 타입에 대한 처리
                processing_mode = options.get('mode', 'premium')
            
            # 마스터 체인 실행
            start_time = time.time()
            result = await self.master_chain.process(
                segments=segments,
                mode=processing_mode,
                custom_options=options
            )
            processing_time = time.time() - start_time
            
            if "error" in result:
                raise Exception(result["error"])
            
            # 결과 데이터 구성
            result_data = {
                "segments": result["segments"],
                "processing_info": {
                    "processing_mode": processing_mode,
                    "processing_time": processing_time,
                    "segment_count": len(result["segments"]),
                    "metadata": result.get("metadata", {})
                }
            }
            
            # 완료 알림
            self.send_result(task_id, "AI_PROCESSING_COMPLETED", data=result_data)
            
            logger.info(f"[{task_id}] Processing completed in {processing_time:.2f}s with mode: {processing_mode}")
            
        except Exception as e:
            logger.error(f"[{task_id}] Processing failed: {e}")
            self.send_result(task_id, "AI_PROCESSING_FAILED", error=str(e))
    
    async def process_request(self, request_data: Dict[str, Any]) -> None:
        """요청 라우팅 및 처리"""
        request_type = request_data.get('type', 'translation')
        
        if request_type == 'translation':
            await self.process_translation_request(request_data)
        else:
            logger.warning(f"Unknown request type: {request_type}")
            task_id = request_data.get('task_id', 'unknown')
            self.send_result(task_id, "AI_PROCESSING_FAILED", error=f"Unknown request type: {request_type}")
    
    def run(self):
        """워커 실행"""
        logger.info("Starting AI Orchestration Worker...")
        
        # Kafka 초기화
        if not self._init_kafka_producer():
            logger.error("Failed to initialize Kafka Producer")
            return
            
        if not self._init_kafka_consumer():
            logger.error("Failed to initialize Kafka Consumer")
            return
        
        # 마스터 체인 초기화
        if not self._init_master_chain():
            logger.error("Failed to initialize master chain")
            return
        
        # 이벤트 루프 설정
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        self.running = True
        logger.info("AI Orchestration Worker started successfully")
        
        try:
            for message in self.consumer:
                if not self.running:
                    break
                    
                try:
                    request_data = message.value
                    logger.info(f"Received AI processing request: {request_data.get('task_id', 'unknown')}")
                    
                    # 비동기 처리
                    loop.run_until_complete(self.process_request(request_data))
                    
                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)
                    
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user")
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
        finally:
            self.stop()
    
    def stop(self):
        """워커 정지"""
        logger.info("Stopping AI Orchestration Worker...")
        self.running = False
        
        if self.consumer:
            self.consumer.close()
        if self.producer:
            self.producer.close()
            
        logger.info("AI Orchestration Worker stopped")

if __name__ == "__main__":
    worker = AIOrchestrationWorker()
    worker.run()