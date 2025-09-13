"""
AI Orchestrator 메인 애플리케이션
LangChain 기반 AI 에이전트들을 관리하고 번역 및 후처리 작업을 수행
"""
import logging
import asyncio
import json
import time
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import (
    KAFKA_BOOTSTRAP_SERVERS,
    AI_PROCESSING_REQUEST_TOPIC,
    AI_PROCESSING_RESULT_TOPIC,
    MAX_CONCURRENT_TASKS,
    LOG_LEVEL,
    CIRCUIT_BREAKER_ENABLED,
    QUOTA_MANAGEMENT_ENABLED
)
from .agents.translator import TranslatorAgent
from .agents.summarizer import SummarizerAgent
from .agents.formatter import FormatterAgent
from .agents.reviewer import ReviewerAgent
from .chains.master_chain import MasterChain, ProcessingMode
from .utils.api_tracker import get_api_tracker
from .utils.circuit_breaker import get_circuit_breaker_manager

# 로깅 설정
logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper()))
logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title="AI Orchestrator Service",
    description="LangChain 기반 AI 에이전트 오케스트레이션 서비스",
    version="1.0.0"
)

# 전역 에이전트 및 체인 인스턴스
translator_agent = None
summarizer_agent = None
formatter_agent = None
reviewer_agent = None
master_chain = None

@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 초기화"""
    global translator_agent, summarizer_agent, formatter_agent, reviewer_agent, master_chain
    
    logger.info("Initializing AI Orchestrator Service...")
    
    # 모든 에이전트 초기화
    translator_agent = TranslatorAgent()
    summarizer_agent = SummarizerAgent()
    formatter_agent = FormatterAgent()
    reviewer_agent = ReviewerAgent()
    
    # 에이전트 상태 로깅
    agents_status = {
        "translator": translator_agent.is_available(),
        "summarizer": summarizer_agent.is_available(),
        "formatter": formatter_agent.is_available(),
        "reviewer": reviewer_agent.is_available()
    }
    
    logger.info(f"Agents status: {agents_status}")
    
    # 마스터 체인 초기화
    master_chain = MasterChain()
    
    if master_chain.is_available():
        logger.info("Master chain initialized successfully")
    else:
        logger.warning("Master chain initialization failed")
    
    logger.info("AI Orchestrator Service startup completed")

@app.on_event("shutdown") 
async def shutdown_event():
    """애플리케이션 종료 시 정리"""
    logger.info("Shutting down AI Orchestrator Service...")

# API 모델 정의
class ProcessingRequest(BaseModel):
    segments: List[Dict[str, Any]] = Field(..., description="STT 결과 세그먼트 리스트")
    task_id: str = Field(..., description="작업 ID")
    mode: str = Field(default="standard", description="처리 모드 (fast, standard, premium, custom)")
    options: Dict[str, Any] = Field(default_factory=dict, description="추가 옵션")

class ProcessingResponse(BaseModel):
    task_id: str
    status: str
    segments: List[Dict[str, Any]]
    metadata: Dict[str, Any]

# 기존 호환성을 위한 별칭
TranslationRequest = ProcessingRequest
TranslationResponse = ProcessingResponse

# API 엔드포인트
@app.get("/health")
async def health_check():
    """헬스체크 엔드포인트"""
    health_status = {
        "status": "healthy",
        "service": "ai-orchestrator",
        "timestamp": time.time(),
        "agents": {}
    }
    
    # 각 에이전트 상태 확인
    agents = {
        "translator": translator_agent,
        "summarizer": summarizer_agent,
        "formatter": formatter_agent,
        "reviewer": reviewer_agent
    }
    
    for agent_name, agent in agents.items():
        if agent:
            health_status["agents"][agent_name] = agent.get_agent_info()
        else:
            health_status["agents"][agent_name] = {"status": "not_initialized"}
            if agent_name == "translator":  # 번역은 필수
                health_status["status"] = "degraded"
    
    # 마스터 체인 상태
    if master_chain:
        health_status["master_chain"] = master_chain.get_chain_info()
    else:
        health_status["master_chain"] = {"status": "not_initialized"}
        health_status["status"] = "degraded"
    
    return health_status

@app.post("/process", response_model=ProcessingResponse)
async def process_segments(request: ProcessingRequest):
    """마스터 체인을 통한 통합 처리 API"""
    if not master_chain or not master_chain.is_available():
        raise HTTPException(
            status_code=503, 
            detail="Master chain is not available"
        )
    
    try:
        logger.info(f"[{request.task_id}] Starting processing: mode={request.mode}, segments={len(request.segments)}")
        
        # 처리 모드 검증
        try:
            processing_mode = ProcessingMode(request.mode)
        except ValueError:
            logger.warning(f"[{request.task_id}] Invalid mode '{request.mode}', using STANDARD")
            processing_mode = ProcessingMode.STANDARD
        
        # 마스터 체인 실행
        result = await master_chain.process(
            segments=request.segments,
            mode=processing_mode,
            custom_options=request.options
        )
        
        if "error" in result:
            raise HTTPException(
                status_code=500,
                detail=result["error"]
            )
        
        logger.info(f"[{request.task_id}] Processing completed successfully")
        
        return ProcessingResponse(
            task_id=request.task_id,
            status="completed",
            segments=result["segments"],
            metadata=result.get("metadata", {})
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{request.task_id}] Processing failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Processing failed: {str(e)}"
        )

@app.post("/translate", response_model=TranslationResponse)
async def translate_segments(request: TranslationRequest):
    """레거시 번역 API (하위 호환성)"""
    # process 엔드포인트로 리다이렉트 (fast 모드 사용)
    processing_request = ProcessingRequest(
        segments=request.segments,
        task_id=request.task_id,
        mode="fast",  # 빠른 번역만
        options=request.options
    )
    
    return await process_segments(processing_request)

@app.get("/agents/status")
async def get_agents_status():
    """모든 에이전트 상태 조회 (Circuit Breaker 상태 포함)"""
    agents_status = {}
    
    agents = {
        "translator": translator_agent,
        "summarizer": summarizer_agent,
        "formatter": formatter_agent,
        "reviewer": reviewer_agent
    }
    
    for agent_name, agent in agents.items():
        if agent:
            agents_status[agent_name] = agent.get_agent_info()
    
    # Circuit Breaker 상태 추가
    circuit_breaker_status = {}
    if CIRCUIT_BREAKER_ENABLED:
        try:
            circuit_breaker_manager = get_circuit_breaker_manager()
            circuit_breaker_status = circuit_breaker_manager.get_all_status()
        except Exception as e:
            logger.warning(f"Failed to get circuit breaker status: {e}")
    
    # API 추적 정보 추가
    api_tracker_status = {}
    if QUOTA_MANAGEMENT_ENABLED:
        try:
            api_tracker = get_api_tracker()
            api_tracker_status = api_tracker.get_session_stats()
        except Exception as e:
            logger.warning(f"Failed to get API tracker status: {e}")
    
    return {
        "total_agents": len(agents_status),
        "agents": agents_status,
        "master_chain": master_chain.get_chain_info() if master_chain else None,
        "circuit_breakers": circuit_breaker_status,
        "api_tracker": api_tracker_status,
        "optimization_features": {
            "circuit_breaker_enabled": CIRCUIT_BREAKER_ENABLED,
            "quota_management_enabled": QUOTA_MANAGEMENT_ENABLED
        }
    }

@app.get("/processing-modes")
async def get_processing_modes():
    """사용 가능한 처리 모드 조회"""
    return {
        "modes": [mode.value for mode in ProcessingMode],
        "mode_descriptions": {
            "fast": "번역만 (빠른 처리)",
            "standard": "번역 + 기본 후처리 (요약, 포맷팅)",
            "premium": "번역 + 검토 + 전체 후처리 (요약, 포맷팅, 하이라이트, 화자 인식)",
            "custom": "사용자 정의 옵션"
        }
    }

@app.post("/process/batch")
async def process_batch(requests: List[ProcessingRequest]):
    """배치 처리 API"""
    if not master_chain or not master_chain.is_available():
        raise HTTPException(
            status_code=503,
            detail="Master chain is not available"
        )
    
    try:
        logger.info(f"Starting batch processing: {len(requests)} requests")
        
        # 배치 요청을 마스터 체인 형식으로 변환
        batch_data = []
        for request in requests:
            try:
                processing_mode = ProcessingMode(request.mode)
            except ValueError:
                processing_mode = ProcessingMode.STANDARD
            
            batch_data.append({
                "segments": request.segments,
                "mode": processing_mode,
                "options": request.options
            })
        
        # 배치 처리 실행 (실제로는 개별 처리를 병렬로)
        results = []
        for i, request in enumerate(requests):
            result = await master_chain.process(
                segments=request.segments,
                mode=ProcessingMode(request.mode) if request.mode in [m.value for m in ProcessingMode] else ProcessingMode.STANDARD,
                custom_options=request.options
            )
            
            results.append(ProcessingResponse(
                task_id=request.task_id,
                status="completed" if "error" not in result else "failed",
                segments=result.get("segments", request.segments),
                metadata=result.get("metadata", {"error": result.get("error")})
            ))
        
        logger.info(f"Batch processing completed: {len(results)} results")
        return {"results": results}
        
    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Batch processing failed: {str(e)}"
        )

# ==================== 비용 모니터링 API ====================

@app.get("/cost/summary")
async def get_cost_summary():
    """API 비용 요약 정보 조회 (AI Agent별 세부 정보 포함)"""
    try:
        tracker = get_api_tracker()
        summary = await tracker.get_cost_summary()
        
        # Agent별 상세 통계 추가
        agent_details = await _get_agent_cost_breakdown()
        summary["agent_breakdown"] = agent_details
        
        return summary
    except Exception as e:
        logger.error(f"Failed to get cost summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def _get_agent_cost_breakdown():
    """Agent별 비용 분석"""
    try:
        tracker = get_api_tracker()
        session_stats = tracker.get_session_stats()
        
        agent_breakdown = {}
        
        # 각 Agent별 통계 계산
        for agent_name, agent_stats in session_stats.get("calls_by_agent", {}).items():
            agent_breakdown[agent_name] = {
                "calls": agent_stats["calls"],
                "tokens": agent_stats["tokens"],
                "cost_usd": agent_stats["cost_usd"],
                "cost_krw": agent_stats["cost_krw"],
                "avg_tokens_per_call": agent_stats["tokens"] / agent_stats["calls"] if agent_stats["calls"] > 0 else 0,
                "avg_cost_per_call_krw": agent_stats["cost_krw"] / agent_stats["calls"] if agent_stats["calls"] > 0 else 0
            }
        
        return agent_breakdown
    except Exception as e:
        logger.warning(f"Failed to get agent breakdown: {e}")
        return {}

@app.get("/cost/logs")
async def get_cost_logs(
    task_id: str = None,
    hours: int = 24,
    agent: str = None
):
    """API 비용 로그 조회"""
    try:
        tracker = get_api_tracker()
        logs = await tracker.get_cost_logs(task_id=task_id, hours=hours, agent=agent)
        return {
            "logs": logs,
            "filter": {
                "task_id": task_id,
                "hours": hours,
                "agent": agent
            }
        }
    except Exception as e:
        logger.error(f"Failed to get cost logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class CostAlertSettings(BaseModel):
    """비용 알림 설정 모델"""
    daily_limit: float = Field(default=10.0, description="일일 비용 한도 (USD)")
    hourly_limit: float = Field(default=2.0, description="시간당 비용 한도 (USD)")
    api_call_limit: int = Field(default=1000, description="API 호출 횟수 한도")
    enabled: bool = Field(default=True, description="알림 활성화 여부")

@app.get("/cost/alerts")
async def get_cost_alerts():
    """비용 알림 설정 및 현재 상태 조회"""
    try:
        tracker = get_api_tracker()
        alerts_status = await tracker.get_alerts_status()
        return alerts_status
    except Exception as e:
        logger.error(f"Failed to get cost alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/cost/alerts")
async def set_cost_alerts(settings: CostAlertSettings):
    """비용 알림 임계치 설정"""
    try:
        tracker = get_api_tracker()
        await tracker.set_alert_thresholds(
            daily_limit=settings.daily_limit,
            hourly_limit=settings.hourly_limit,
            api_call_limit=settings.api_call_limit,
            enabled=settings.enabled
        )
        
        return {
            "message": "Cost alert settings updated successfully",
            "settings": settings.dict()
        }
    except Exception as e:
        logger.error(f"Failed to set cost alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== 새로운 세부 분석 API ====================

@app.get("/cost/agent-performance")
async def get_agent_performance_analysis():
    """AI Agent별 성능 및 비용 효율성 분석"""
    try:
        tracker = get_api_tracker()
        logs = await tracker.get_cost_logs(hours=24)
        
        # Agent별 성능 지표 계산
        agent_performance = {}
        
        for log in logs:
            agent_name = log.get("agent_name", "unknown")
            
            if agent_name not in agent_performance:
                agent_performance[agent_name] = {
                    "total_calls": 0,
                    "successful_calls": 0,
                    "failed_calls": 0,
                    "total_tokens": 0,
                    "total_cost_krw": 0,
                    "total_processing_time_ms": 0,
                    "functions": {}
                }
            
            perf = agent_performance[agent_name]
            perf["total_calls"] += 1
            perf["total_tokens"] += log.get("total_tokens", 0)
            perf["total_cost_krw"] += log.get("estimated_cost_krw", 0)
            perf["total_processing_time_ms"] += log.get("processing_time_ms", 0)
            
            if log.get("success"):
                perf["successful_calls"] += 1
            else:
                perf["failed_calls"] += 1
            
            # Function별 세부 분석
            function_name = log.get("function_name", "unknown")
            if function_name not in perf["functions"]:
                perf["functions"][function_name] = {
                    "calls": 0,
                    "avg_tokens": 0,
                    "avg_cost_krw": 0,
                    "avg_processing_time_ms": 0
                }
            
            func_stats = perf["functions"][function_name]
            func_stats["calls"] += 1
        
        # 효율성 지표 계산
        for agent_name, perf in agent_performance.items():
            if perf["total_calls"] > 0:
                perf["success_rate"] = perf["successful_calls"] / perf["total_calls"]
                perf["avg_tokens_per_call"] = perf["total_tokens"] / perf["total_calls"]
                perf["avg_cost_per_call_krw"] = perf["total_cost_krw"] / perf["total_calls"]
                perf["avg_processing_time_per_call_ms"] = perf["total_processing_time_ms"] / perf["total_calls"]
                perf["cost_per_token_krw"] = perf["total_cost_krw"] / perf["total_tokens"] if perf["total_tokens"] > 0 else 0
            
            # Function별 평균 계산
            for func_name, func_stats in perf["functions"].items():
                if func_stats["calls"] > 0:
                    # 해당 function의 모든 로그를 다시 집계
                    func_logs = [log for log in logs if log.get("agent_name") == agent_name and log.get("function_name") == func_name]
                    
                    if func_logs:
                        func_stats["avg_tokens"] = sum(log.get("total_tokens", 0) for log in func_logs) / len(func_logs)
                        func_stats["avg_cost_krw"] = sum(log.get("estimated_cost_krw", 0) for log in func_logs) / len(func_logs)
                        func_stats["avg_processing_time_ms"] = sum(log.get("processing_time_ms", 0) for log in func_logs) / len(func_logs)
        
        return {
            "agent_performance": agent_performance,
            "analysis_period": "24h",
            "total_agents_analyzed": len(agent_performance)
        }
        
    except Exception as e:
        logger.error(f"Failed to get agent performance analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cost/mode-comparison")
async def get_processing_mode_comparison():
    """번역 모드별 비용 및 성능 비교 분석"""
    try:
        tracker = get_api_tracker()
        logs = await tracker.get_cost_logs(hours=24)
        
        # task_id에서 모드 정보 추출 (task_id에 모드 정보가 포함되어 있다고 가정)
        mode_analysis = {
            "fast": {
                "tasks": 0,
                "total_cost_krw": 0,
                "total_tokens": 0,
                "total_processing_time_ms": 0,
                "avg_agents_used": 0,
                "agents_breakdown": {}
            },
            "standard": {
                "tasks": 0,
                "total_cost_krw": 0,
                "total_tokens": 0,
                "total_processing_time_ms": 0,
                "avg_agents_used": 0,
                "agents_breakdown": {}
            },
            "premium": {
                "tasks": 0,
                "total_cost_krw": 0,
                "total_tokens": 0,
                "total_processing_time_ms": 0,
                "avg_agents_used": 0,
                "agents_breakdown": {}
            }
        }
        
        # 태스크별로 그룹화
        task_groups = {}
        for log in logs:
            task_id = log.get("task_id", "unknown")
            if task_id not in task_groups:
                task_groups[task_id] = []
            task_groups[task_id].append(log)
        
        # 각 태스크의 모드 추정 및 분석
        for task_id, task_logs in task_groups.items():
            # 사용된 Agent 수로 모드 추정
            agents_used = set(log.get("agent_name") for log in task_logs)
            
            estimated_mode = "fast"  # 기본값
            if "ReviewerAgent" in agents_used or len(agents_used) >= 4:
                estimated_mode = "premium"
            elif "SummarizerAgent" in agents_used or "FormatterAgent" in agents_used:
                estimated_mode = "standard"
            
            mode_data = mode_analysis[estimated_mode]
            mode_data["tasks"] += 1
            mode_data["avg_agents_used"] += len(agents_used)
            
            for log in task_logs:
                mode_data["total_cost_krw"] += log.get("estimated_cost_krw", 0)
                mode_data["total_tokens"] += log.get("total_tokens", 0)
                mode_data["total_processing_time_ms"] += log.get("processing_time_ms", 0)
                
                # Agent별 분석
                agent_name = log.get("agent_name", "unknown")
                if agent_name not in mode_data["agents_breakdown"]:
                    mode_data["agents_breakdown"][agent_name] = {
                        "calls": 0,
                        "total_cost_krw": 0,
                        "total_tokens": 0
                    }
                
                agent_breakdown = mode_data["agents_breakdown"][agent_name]
                agent_breakdown["calls"] += 1
                agent_breakdown["total_cost_krw"] += log.get("estimated_cost_krw", 0)
                agent_breakdown["total_tokens"] += log.get("total_tokens", 0)
        
        # 평균 계산
        for mode, data in mode_analysis.items():
            if data["tasks"] > 0:
                data["avg_cost_per_task_krw"] = data["total_cost_krw"] / data["tasks"]
                data["avg_tokens_per_task"] = data["total_tokens"] / data["tasks"]
                data["avg_processing_time_per_task_ms"] = data["total_processing_time_ms"] / data["tasks"]
                data["avg_agents_used"] = data["avg_agents_used"] / data["tasks"]
        
        return {
            "mode_comparison": mode_analysis,
            "analysis_period": "24h",
            "total_tasks_analyzed": sum(data["tasks"] for data in mode_analysis.values())
        }
        
    except Exception as e:
        logger.error(f"Failed to get mode comparison: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cost/research-stats")
async def get_research_statistics():
    """논문 작성용 연구 통계 데이터"""
    try:
        tracker = get_api_tracker()
        logs = await tracker.get_cost_logs(hours=168)  # 최근 1주일
        
        # 연구용 통계 계산
        research_stats = {
            "total_api_calls": len(logs),
            "unique_tasks": len(set(log.get("task_id") for log in logs)),
            "total_cost_krw": sum(log.get("estimated_cost_krw", 0) for log in logs),
            "total_tokens": sum(log.get("total_tokens", 0) for log in logs),
            "average_response_time_ms": sum(log.get("processing_time_ms", 0) for log in logs) / len(logs) if logs else 0,
            "success_rate": sum(1 for log in logs if log.get("success")) / len(logs) if logs else 0,
            
            # 모델별 사용량
            "model_usage": {},
            "agent_efficiency": {},
            "daily_usage_pattern": {},
            
            # 비용 효율성 지표
            "cost_per_successful_translation": 0,
            "tokens_per_krw": 0,
            "agent_utilization_rate": {}
        }
        
        # 모델별 통계
        for log in logs:
            model = log.get("model_name", "unknown")
            if model not in research_stats["model_usage"]:
                research_stats["model_usage"][model] = {
                    "calls": 0,
                    "total_cost_krw": 0,
                    "total_tokens": 0,
                    "avg_response_time_ms": 0
                }
            
            model_stats = research_stats["model_usage"][model]
            model_stats["calls"] += 1
            model_stats["total_cost_krw"] += log.get("estimated_cost_krw", 0)
            model_stats["total_tokens"] += log.get("total_tokens", 0)
        
        # 평균 계산
        for model, stats in research_stats["model_usage"].items():
            if stats["calls"] > 0:
                model_logs = [log for log in logs if log.get("model_name") == model]
                stats["avg_response_time_ms"] = sum(log.get("processing_time_ms", 0) for log in model_logs) / len(model_logs)
                stats["cost_per_token_krw"] = stats["total_cost_krw"] / stats["total_tokens"] if stats["total_tokens"] > 0 else 0
        
        # 전체 효율성 지표
        successful_calls = [log for log in logs if log.get("success")]
        if successful_calls:
            research_stats["cost_per_successful_translation"] = research_stats["total_cost_krw"] / len(successful_calls)
        
        if research_stats["total_cost_krw"] > 0:
            research_stats["tokens_per_krw"] = research_stats["total_tokens"] / research_stats["total_cost_krw"]
        
        # Agent 활용률
        total_agents = 4  # TranslatorAgent, SummarizerAgent, FormatterAgent, ReviewerAgent
        unique_agents_used = len(set(log.get("agent_name") for log in logs))
        research_stats["agent_utilization_rate"]["unique_agents_used"] = unique_agents_used
        research_stats["agent_utilization_rate"]["utilization_percentage"] = (unique_agents_used / total_agents) * 100
        
        return research_stats
        
    except Exception as e:
        logger.error(f"Failed to get research statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 에러 핸들러
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return HTTPException(
        status_code=500,
        detail="Internal server error"
    )