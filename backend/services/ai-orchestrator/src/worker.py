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
from .utils.api_tracker import get_api_tracker

# 로깅 설정
logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper()))
logger = logging.getLogger(__name__)

# System metrics logger (local adapter)
from .system_logger_adapter import (
    log_kafka_message,
    log_timeline,
    log_performance,
)
class AIOrchestrationWorker:
    """AI 오케스트레이션 워커 - 최신 요청 우선 처리"""
    
    def __init__(self):
        self.producer = None
        self.consumer = None
        self.master_chain = None
        self.running = False
        # 현재 처리 중인 작업 취소를 위한 이벤트
        self.current_task_cancel_event = asyncio.Event()
        self.current_task_id = None
        self.processing_tasks = set()
        
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
                    group_id='ai_orchestrator_workers_priority',  # 새로운 그룹
                    auto_offset_reset='latest'  # 최신 메시지부터
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
    
    def send_result(self, task_id: str, status: str, data: Any = None, error: str = None, ai_agents: Any = None, progress_detail: str = None):
        """처리 결과를 Kafka로 전송 (AI 에이전트 정보 포함)"""
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
        if ai_agents is not None:
            message["ai_agents"] = ai_agents
        if progress_detail is not None:
            message["progress_detail"] = progress_detail
            
        try:
            self.producer.send(
                AI_PROCESSING_RESULT_TOPIC,
                value=message,
                key=task_id.encode('utf-8')
            )
            self.producer.flush()
            logger.info(f"[{task_id}] Result sent: {status} - {progress_detail or 'No detail'}")
            # system metrics: kafka + timeline
            try:
                log_kafka_message(task_id, topic=AI_PROCESSING_RESULT_TOPIC, message=status)
                if progress_detail:
                    log_timeline(task_id, agent="ai-orchestrator", task=progress_detail, progress=0)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"[{task_id}] Failed to send result: {e}")
    
    def send_agent_status_update(self, task_id: str, agent_status: Dict[str, Any]):
        """AI 에이전트 상태 업데이트 전송 (API 통계 포함)"""
        # API 사용 통계 실시간 수집
        api_tracker = get_api_tracker()
        api_stats = api_tracker.get_session_stats()
        
        ai_agent_data = {
            "agents": agent_status.get("agents", {}),
            "summary": {
                **agent_status.get("summary", {}),
                "real_time_api_usage": {
                    "total_calls": api_stats.get("total_calls", 0),
                    "total_tokens": api_stats.get("total_tokens", 0),
                    "total_cost_krw": api_stats.get("total_cost_krw", 0.0),
                    "calls_by_agent": api_stats.get("calls_by_agent", {}),
                    "calls_by_model": api_stats.get("calls_by_model", {}),
                    "errors": api_stats.get("errors", 0)
                }
            },
            "current_stage": agent_status.get("current_stage", ""),
            "stage_details": agent_status.get("stage_details", {}),
            "processing_metrics": {
                "elapsed_time": time.time() - agent_status.get("summary", {}).get("startTime", time.time()),
                "estimated_completion": agent_status.get("estimated_completion", "unknown"),
                "tokens_processed": agent_status.get("tokens_processed", 0),
                "segments_completed": agent_status.get("segments_completed", 0)
            }
        }
        
        # 상세한 진행 상태 정보 생성
        progress_detail = f"{agent_status.get('current_stage', 'Processing')} ({agent_status.get('segments_completed', 0)}개 완료)"
        
        self.send_result(
            task_id=task_id,
            status="AI_PROCESSING",
            ai_agents=ai_agent_data,
            progress_detail=progress_detail
        )
    
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
            self.send_result(task_id, "AI_PROCESSING_STARTED", progress_detail="AI 번역 시작")
            
            # 처리 모드 결정
            if request_type == 'translation':
                # 기본 번역 요청은 standard 모드
                processing_mode = options.get('mode', 'standard')
            else:
                # 기타 요청 타입에 대한 처리
                processing_mode = options.get('mode', 'premium')
            
            # 마스터 체인 실행 (콜백으로 실시간 상태 업데이트)
            start_time = time.time()
            
            # 에이전트 상태 추적을 위한 콜백 함수
            def status_callback(agent_status):
                self.send_agent_status_update(task_id, agent_status)
            
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
            try:
                # performance metric for AI phase
                log_performance(task_id, {"ai_processing_time": processing_time})
                log_timeline(task_id, agent="ai-orchestrator", task="AI 처리 완료", progress=100, duration=processing_time)
            except Exception:
                pass
            
            logger.info(f"[{task_id}] Processing completed in {processing_time:.2f}s with mode: {processing_mode}")
            
        except Exception as e:
            logger.error(f"[{task_id}] Processing failed: {e}")
            # API 오류인지 확인
            error_detail = str(e)
            if "429" in error_detail or "quota" in error_detail.lower():
                progress_detail = "API 한도 초과 - 잠시 후 재시도"
            elif "ResourceExhausted" in error_detail:
                progress_detail = "API 리소스 고갈 - 모델 전환 시도 중"
            else:
                progress_detail = f"처리 오류: {error_detail[:50]}..."
                
            self.send_result(task_id, "AI_PROCESSING_FAILED", error=str(e), progress_detail=progress_detail)
    
    async def process_stt_completion_request(self, request_data: Dict[str, Any]) -> None:
        """STT 완료 후 AI 처리 요청"""
        task_id = request_data.get('task_id')
        segments = request_data.get('segments', [])
        mode = request_data.get('mode', 'standard')
        custom_settings = request_data.get('custom_settings', {})
        
        if not task_id:
            logger.error("Received STT completion request without task_id")
            return
            
        logger.info(f"[{task_id}] Processing STT completion request with mode: {mode}")
        
        # 모드별 에이전트 정보 초기화
        agent_info = self.get_mode_agents(mode, custom_settings)
        
        # 초기 에이전트 상태 전송
        initial_status = {
            "agents": agent_info,
            "summary": {
                "mode": mode,
                "totalAgents": len(agent_info),
                "startTime": time.time()
            },
            "current_stage": "초기화 중"
        }
        self.send_agent_status_update(task_id, initial_status)
        
        # 기존 translation request 형태로 변환하여 처리
        translation_request = {
            "task_id": task_id,
            "segments": segments,
            "type": "translation",
            "options": {
                "mode": mode,
                "custom_settings": custom_settings
            }
        }
        
        await self.process_translation_request(translation_request)
    
    async def process_sentence_first_request(self, request_data: Dict[str, Any]) -> None:
        """새로운 sentence-first 워크플로우 처리"""
        task_id = request_data.get('task_id')
        raw_text = request_data.get('raw_text', '')
        word_timestamps = request_data.get('word_timestamps', [])
        mode = request_data.get('mode', 'standard')
        custom_settings = request_data.get('custom_settings', {})
        
        if not task_id:
            logger.error("Received sentence-first request without task_id")
            return
            
        logger.info(f"[{task_id}] Processing sentence-first request with mode: {mode}")
        
        try:
            # 취소 확인
            if self.current_task_cancel_event.is_set():
                logger.info(f"[{task_id}] AI task cancelled before processing")
                return
                
            # Sentence Segmentation Agent를 포함한 에이전트 정보 초기화
            agent_info = self.get_sentence_first_agents(mode, custom_settings)
            
            # 취소 확인
            if self.current_task_cancel_event.is_set():
                logger.info(f"[{task_id}] AI task cancelled during initialization")
                return
            
            # 초기 에이전트 상태 전송
            initial_status = {
                "agents": agent_info,
                "summary": {
                    "mode": mode,
                    "workflow_type": "sentence_first",
                    "totalAgents": len(agent_info),
                    "startTime": time.time(),
                    "textLength": len(raw_text),
                    "estimatedTokens": int(len(raw_text) * 1.2)
                },
                "current_stage": "문장 분할 초기화 중"
            }
            self.send_agent_status_update(task_id, initial_status)
            
            # 상태 콜백 함수
            def status_callback(status_data):
                agent_status = {
                    "agents": self.update_agent_status_from_workflow(agent_info, status_data),
                    "summary": {
                        **initial_status["summary"],
                        "currentStage": status_data.get("current_stage", ""),
                        "progress": status_data.get("progress", 0)
                    },
                    "current_stage": status_data.get("current_stage", ""),
                    "stage_details": {
                        "message": status_data.get("details", {}).get("message", ""),
                        "segment_count": status_data.get("details", {}).get("segment_count", 0),
                        "group_count": status_data.get("details", {}).get("group_count", 0),
                        "estimated_cost": status_data.get("details", {}).get("estimated_cost", 0),
                        "success_count": status_data.get("details", {}).get("success_count", 0),
                        "quota_exceeded": status_data.get("details", {}).get("quota_exceeded", False)
                    },
                    "tokens_processed": status_data.get("details", {}).get("estimated_cost", 0) * 1000,
                    "segments_completed": status_data.get("details", {}).get("success_count", 0)
                }
                self.send_agent_status_update(task_id, agent_status)
            
            # 취소 확인
            if self.current_task_cancel_event.is_set():
                logger.info(f"[{task_id}] AI task cancelled before master chain processing")
                return
            
            # 마스터 체인에 취소 이벤트 전달
            result = await self.master_chain.process_sentence_first_workflow(
                raw_text=raw_text,
                word_timestamps=word_timestamps,
                mode=mode,
                custom_options=custom_settings,
                status_callback=status_callback,
                task_id=task_id,  # task_id 전달 추가
                cancel_event=self.current_task_cancel_event  # 취소 이벤트 전달
            )
            
            # 취소 확인
            if self.current_task_cancel_event.is_set():
                logger.info(f"[{task_id}] AI task cancelled after processing")
                return
                
            if "error" in result:
                # 오류인지 취소인지 확인
                if "cancelled" in result["error"].lower():
                    logger.info(f"[{task_id}] AI processing was cancelled")
                    return
                raise Exception(result["error"])
            
            # API 사용 통계 수집
            api_tracker = get_api_tracker()
            api_stats = api_tracker.get_session_stats()
            
            # 결과 데이터 구성
            result_data = {
                "segments": result["segments"],
                "processing_info": {
                    "workflow_type": "sentence_first",
                    "processing_mode": mode,
                    "processing_time": result["metadata"].get("processing_time", 0),
                    "segment_count": len(result["segments"]),
                    "success_rate": result["metadata"].get("success_rate", 0),
                    "estimated_tokens": result["metadata"].get("estimated_tokens", 0),
                    "api_usage": {
                        "total_calls": api_stats.get("total_calls", 0),
                        "total_tokens": api_stats.get("total_tokens", 0),
                        "total_cost_usd": api_stats.get("total_cost_usd", 0.0),
                        "total_cost_krw": api_stats.get("total_cost_krw", 0.0),
                        "calls_by_agent": api_stats.get("calls_by_agent", {}),
                        "calls_by_model": api_stats.get("calls_by_model", {}),
                        "errors": api_stats.get("errors", 0)
                    },
                    "metadata": result.get("metadata", {})
                }
            }
            
            # 마지막 취소 확인
            if self.current_task_cancel_event.is_set():
                logger.info(f"[{task_id}] AI task cancelled before sending completion result")
                return
            
            # 완료 알림
            self.send_result(task_id, "AI_PROCESSING_COMPLETED", data=result_data)
            try:
                ai_ptime = result.get("metadata", {}).get("processing_time", 0)
                if not ai_ptime:
                    ai_ptime = result_data.get("processing_info", {}).get("processing_time", 0)
                log_performance(task_id, {"ai_processing_time": ai_ptime})
                log_timeline(task_id, agent="ai-orchestrator", task="Sentence-first 처리 완료", progress=100, duration=ai_ptime)
            except Exception:
                pass
            
            logger.info(f"[{task_id}] Sentence-first processing completed successfully")
            
        except Exception as e:
            logger.error(f"[{task_id}] Sentence-first processing failed: {e}")
            self.send_result(task_id, "AI_PROCESSING_FAILED", error=str(e))
    
    def get_sentence_first_agents(self, mode: str, custom_settings: dict) -> Dict[str, Any]:
        """sentence-first 워크플로우용 에이전트 정보 반환"""
        base_agents = {
            "sentence_segmenter": {
                "name": "SentenceSegmentationAgent",
                "icon": "🔤",
                "description": "AI 기반 지능형 문장 분할",
                "status": "waiting",
                "progress": 0
            },
            "translator": {
                "name": "TranslatorAgent", 
                "icon": "🌐",
                "description": "그룹별 최적화 번역",
                "status": "waiting",
                "progress": 0
            }
        }
        
        # 모드에 따른 추가 에이전트
        if mode == "standard":
            base_agents.update({
                "summarizer": {
                    "name": "SummarizerAgent",
                    "icon": "📝", 
                    "description": "내용 요약 및 키워드 추출",
                    "status": "waiting",
                    "progress": 0
                },
                "formatter": {
                    "name": "FormatterAgent",
                    "icon": "✨",
                    "description": "자막 서식 개선", 
                    "status": "waiting",
                    "progress": 0
                }
            })
        elif mode == "premium":
            base_agents.update({
                "summarizer": {
                    "name": "SummarizerAgent",
                    "icon": "📝",
                    "description": "내용 요약, 키워드, 감정분석",
                    "status": "waiting", 
                    "progress": 0
                },
                "formatter": {
                    "name": "FormatterAgent",
                    "icon": "✨",
                    "description": "자막 서식 개선 및 화자 구분",
                    "status": "waiting",
                    "progress": 0
                },
                "reviewer": {
                    "name": "ReviewerAgent",
                    "icon": "🔍", 
                    "description": "번역 품질 검토 및 개선 제안",
                    "status": "waiting",
                    "progress": 0
                }
            })
        
        return base_agents
    
    def update_agent_status_from_workflow(self, agents: Dict[str, Any], status_data: Dict[str, Any]) -> Dict[str, Any]:
        """워크플로우 상태에서 에이전트 상태 업데이트"""
        updated_agents = agents.copy()
        current_stage = status_data.get("current_stage", "")
        progress = status_data.get("progress", 0)
        
        # 현재 단계에 따른 에이전트 상태 업데이트
        if "sentence_segmentation" in current_stage:
            updated_agents["sentence_segmenter"]["status"] = "processing"
            updated_agents["sentence_segmenter"]["progress"] = min(progress, 30)
        elif "translation_optimization" in current_stage:
            updated_agents["sentence_segmenter"]["status"] = "completed"
            updated_agents["sentence_segmenter"]["progress"] = 100
            updated_agents["translator"]["status"] = "processing" 
            updated_agents["translator"]["progress"] = max(0, progress - 30)
        elif "batch_translation" in current_stage:
            updated_agents["translator"]["status"] = "processing"
            updated_agents["translator"]["progress"] = max(0, progress - 50)
        elif "post_processing" in current_stage:
            updated_agents["translator"]["status"] = "completed"
            updated_agents["translator"]["progress"] = 100
            if "summarizer" in updated_agents:
                updated_agents["summarizer"]["status"] = "processing"
            if "formatter" in updated_agents:
                updated_agents["formatter"]["status"] = "processing"
        elif current_stage == "completed":
            # 모든 에이전트 완료
            for agent_id in updated_agents:
                updated_agents[agent_id]["status"] = "completed"
                updated_agents[agent_id]["progress"] = 100
        
        return updated_agents
    
    def get_mode_agents(self, mode: str, custom_settings: dict) -> Dict[str, Any]:
        """모드별 에이전트 정보 반환"""
        base_agents = {
            "translator": {
                "name": "TranslatorAgent",
                "icon": "🌐",
                "description": "일본어 → 한국어 번역",
                "status": "waiting",
                "progress": 0
            }
        }
        
        if mode == "standard":
            base_agents.update({
                "summarizer": {
                    "name": "SummarizerAgent", 
                    "icon": "📝",
                    "description": "내용 요약 및 키워드 추출",
                    "status": "waiting",
                    "progress": 0
                },
                "formatter": {
                    "name": "FormatterAgent",
                    "icon": "✨", 
                    "description": "자막 서식 개선",
                    "status": "waiting",
                    "progress": 0
                }
            })
        elif mode == "premium":
            base_agents.update({
                "summarizer": {
                    "name": "SummarizerAgent",
                    "icon": "📝",
                    "description": "내용 요약, 키워드, 감정분석", 
                    "status": "waiting",
                    "progress": 0
                },
                "formatter": {
                    "name": "FormatterAgent",
                    "icon": "✨",
                    "description": "자막 서식 개선 및 화자 구분",
                    "status": "waiting", 
                    "progress": 0
                },
                "reviewer": {
                    "name": "ReviewerAgent",
                    "icon": "🔍",
                    "description": "번역 품질 검토 및 개선 제안",
                    "status": "waiting",
                    "progress": 0
                }
            })
        elif mode == "custom":
            # 커스텀 설정에 따라 에이전트 추가
            if custom_settings.get("enableSummary"):
                base_agents["summarizer"] = {
                    "name": "SummarizerAgent",
                    "icon": "📝", 
                    "description": "내용 요약 생성",
                    "status": "waiting",
                    "progress": 0
                }
            # 다른 커스텀 설정들도 추가...
        
        return base_agents

    async def process_request(self, request_data: Dict[str, Any]) -> None:
        """요청 라우팅 및 처리"""
        # 새로운 sentence-first 워크플로우 확인
        workflow_type = request_data.get('workflow_type', 'default')
        
        if workflow_type == 'sentence_first':
            await self.process_sentence_first_request(request_data)
            return
        
        # STT 완료 후 AI 처리 요청인지 확인 (기존 방식)
        if 'mode' in request_data and 'segments' in request_data and 'type' not in request_data:
            await self.process_stt_completion_request(request_data)
            return
            
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
                    task_id = request_data.get('task_id', 'unknown')
                    
                    # 기존 작업 취소 및 새로운 작업 시작
                    if self.current_task_id and self.current_task_id != task_id:
                        logger.info(f"Cancelling current AI task {self.current_task_id} for new task {task_id}")
                        self.current_task_cancel_event.set()
                        
                        # 이전 작업에 취소 신호 보내기
                        self._send_cancellation_message(self.current_task_id)
                        
                        # 짧은 대기 후 취소 이벤트 리셋
                        time.sleep(1)
                        self.current_task_cancel_event.clear()
                    
                    # 중복 처리 방지
                    if task_id in self.processing_tasks:
                        logger.warning(f"AI task {task_id} is already being processed, skipping")
                        continue
                    
                    logger.info(f"Starting new priority AI task: {task_id}")
                    self.current_task_id = task_id
                    self.processing_tasks.add(task_id)
                    
                    try:
                        # 비동기 처리
                        loop.run_until_complete(self.process_request(request_data))
                    finally:
                        # 처리 완료 후 태스크 제거
                        self.processing_tasks.discard(task_id)
                        if self.current_task_id == task_id:
                            self.current_task_id = None
                    
                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)
                    
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user")
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
        finally:
            self.stop()
    
    def _send_cancellation_message(self, task_id: str):
        """취소된 AI 작업에 취소 메시지 전송"""
        try:
            result = {
                'task_id': task_id,
                'status': 'AI_PROCESSING_CANCELLED',
                'data': None,
                'error': 'AI task cancelled due to new request priority',
                'service': 'ai-orchestrator'
            }
            
            self.producer.send(AI_PROCESSING_RESULT_TOPIC, value=result)
            self.producer.flush()
            logger.info(f"Sent AI cancellation message for task: {task_id}")
        except Exception as e:
            logger.error(f"Failed to send AI cancellation message: {e}")
    
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
