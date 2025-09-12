"""
Gemini API 호출 추적 및 비용 모니터링 유틸리티
"""
import time
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime
import threading
import os
from functools import wraps

logger = logging.getLogger(__name__)

@dataclass
class APICallLog:
    """API 호출 로그 데이터 클래스"""
    timestamp: str
    task_id: str
    agent_name: str
    function_name: str
    model_name: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    estimated_cost_krw: float
    processing_time_ms: float
    success: bool
    error_message: Optional[str] = None
    context: Optional[Dict[str, Any]] = None

class GeminiAPITracker:
    """Gemini API 호출 추적 및 비용 모니터링"""
    
    # Gemini API 비용 (USD per 1K tokens) - 2024년 기준
    MODEL_COSTS = {
        "gemini-1.5-flash": {
            "input": 0.000075,   # $0.075 per 1M tokens
            "output": 0.0003     # $0.30 per 1M tokens  
        },
        "gemini-1.5-pro": {
            "input": 0.00125,    # $1.25 per 1M tokens
            "output": 0.005      # $5.00 per 1M tokens
        },
        "gemini-2.0-flash": {
            "input": 0.000075,   # 추정값
            "output": 0.0003
        },
        "gemini-pro": {
            "input": 0.0005,     # 기본 모델 추정값
            "output": 0.0015
        }
    }
    
    USD_TO_KRW = 1350  # 환율 (주기적으로 업데이트 필요)
    
    def __init__(self, log_file_path: str = "/app/logs/gemini_api_calls.jsonl"):
        self.log_file_path = log_file_path
        self.session_stats = {
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "total_cost_krw": 0.0,
            "calls_by_agent": {},
            "calls_by_model": {},
            "errors": 0
        }
        self._lock = threading.Lock()
        
        # 로그 디렉토리 생성
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        
        logger.info("Gemini API Tracker initialized")
    
    def estimate_tokens(self, text: str) -> int:
        """개선된 텍스트 토큰 수 추정"""
        if not text:
            return 0
        
        # 언어 감지 (개선된 휴리스틱)
        asian_chars = len([c for c in text if ord(c) > 0x2000])
        asian_ratio = asian_chars / len(text) if len(text) > 0 else 0
        
        # 일본어/한국어 텍스트 처리 (더 정확한 추정)
        if asian_ratio > 0.3:  # 30% 이상이 아시아 문자
            # 일본어: 실제 Gemini는 평균 1.8자당 1토큰
            # 복잡한 문자(한자, 복합 문자)는 더 많은 토큰 소모
            
            # 한자 비율 계산 (더 높은 토큰 소모)
            kanji_chars = len([c for c in text if 0x4E00 <= ord(c) <= 0x9FAF])
            kanji_ratio = kanji_chars / len(text) if len(text) > 0 else 0
            
            # 토큰 계수 계산 (1.5 ~ 2.2 범위)
            base_factor = 1.8  # 기본 계수
            kanji_penalty = kanji_ratio * 0.4  # 한자가 많을수록 토큰 증가
            length_bonus = min(0.2, len(text) / 5000)  # 긴 텍스트일수록 효율적
            
            token_factor = base_factor + kanji_penalty - length_bonus
            return max(1, int(len(text) / token_factor))
        else:
            # 영어: 평균 4자당 1토큰 (기존 유지)
            return max(1, len(text) // 4)
    
    def calculate_cost(self, model_name: str, input_tokens: int, output_tokens: int) -> tuple[float, float]:
        """토큰 수 기반 비용 계산"""
        # 모델명에서 정확한 매치 찾기
        cost_key = None
        for key in self.MODEL_COSTS.keys():
            if key in model_name.lower():
                cost_key = key
                break
        
        if not cost_key:
            # 기본값 사용
            cost_key = "gemini-1.5-flash"
            logger.warning(f"Unknown model {model_name}, using {cost_key} pricing")
        
        costs = self.MODEL_COSTS[cost_key]
        
        # 1K 토큰 당 비용 계산
        input_cost = (input_tokens / 1000) * costs["input"]
        output_cost = (output_tokens / 1000) * costs["output"]
        total_cost_usd = input_cost + output_cost
        total_cost_krw = total_cost_usd * self.USD_TO_KRW
        
        return total_cost_usd, total_cost_krw
    
    def log_api_call(self, log_entry: APICallLog):
        """API 호출 로그 기록"""
        with self._lock:
            # 파일에 로그 기록 (JSONL 형식)
            try:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(log_entry), ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error(f"Failed to write API call log: {e}")
            
            # 세션 통계 업데이트
            self.session_stats["total_calls"] += 1
            self.session_stats["total_tokens"] += log_entry.total_tokens
            self.session_stats["total_cost_usd"] += log_entry.estimated_cost_usd
            self.session_stats["total_cost_krw"] += log_entry.estimated_cost_krw
            
            # 에이전트별 통계
            if log_entry.agent_name not in self.session_stats["calls_by_agent"]:
                self.session_stats["calls_by_agent"][log_entry.agent_name] = {
                    "calls": 0, "tokens": 0, "cost_usd": 0.0, "cost_krw": 0.0
                }
            
            agent_stats = self.session_stats["calls_by_agent"][log_entry.agent_name]
            agent_stats["calls"] += 1
            agent_stats["tokens"] += log_entry.total_tokens
            agent_stats["cost_usd"] += log_entry.estimated_cost_usd
            agent_stats["cost_krw"] += log_entry.estimated_cost_krw
            
            # 모델별 통계
            if log_entry.model_name not in self.session_stats["calls_by_model"]:
                self.session_stats["calls_by_model"][log_entry.model_name] = {
                    "calls": 0, "tokens": 0, "cost_usd": 0.0, "cost_krw": 0.0
                }
            
            model_stats = self.session_stats["calls_by_model"][log_entry.model_name]
            model_stats["calls"] += 1
            model_stats["tokens"] += log_entry.total_tokens
            model_stats["cost_usd"] += log_entry.estimated_cost_usd
            model_stats["cost_krw"] += log_entry.estimated_cost_krw
            
            if not log_entry.success:
                self.session_stats["errors"] += 1
            
            # 상세 로그 출력
            status = "✅ SUCCESS" if log_entry.success else "❌ ERROR"
            logger.info(
                f"🔥 GEMINI API CALL {status} 🔥\n"
                f"  📋 Task: {log_entry.task_id}\n"
                f"  🤖 Agent: {log_entry.agent_name}\n"
                f"  🔧 Function: {log_entry.function_name}\n"
                f"  🧠 Model: {log_entry.model_name}\n"
                f"  📊 Tokens: {log_entry.input_tokens} in + {log_entry.output_tokens} out = {log_entry.total_tokens} total\n"
                f"  💰 Cost: ${log_entry.estimated_cost_usd:.6f} USD (₩{log_entry.estimated_cost_krw:.2f} KRW)\n"
                f"  ⏱️  Time: {log_entry.processing_time_ms:.1f}ms\n"
                f"  📈 Session Total: {self.session_stats['total_calls']} calls, "
                f"₩{self.session_stats['total_cost_krw']:.2f} KRW"
                + (f"\n  🚨 Error: {log_entry.error_message}" if log_entry.error_message else "")
            )
            
            # 비용 경고
            if log_entry.estimated_cost_krw > 100:  # 100원 이상
                logger.warning(f"🚨 HIGH COST CALL: ₩{log_entry.estimated_cost_krw:.2f} KRW for single call!")
            
            if self.session_stats["total_cost_krw"] > 1000:  # 세션 총 1000원 이상
                logger.warning(f"🚨 SESSION COST WARNING: Total ₩{self.session_stats['total_cost_krw']:.2f} KRW")
    
    def get_session_stats(self) -> Dict[str, Any]:
        """현재 세션 통계 반환"""
        with self._lock:
            return self.session_stats.copy()
    
    def track_api_call(self, task_id: str, agent_name: str, function_name: str):
        """API 호출 추적 데코레이터"""
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                
                # 입력 데이터에서 토큰 수 추정
                input_text = ""
                if args:
                    input_text = str(args[0]) if args else ""
                if "prompt" in kwargs:
                    input_text = kwargs["prompt"]
                elif "text" in kwargs:
                    input_text = kwargs["text"]
                
                input_tokens = self.estimate_tokens(input_text)
                
                try:
                    # 실제 API 호출
                    result = await func(*args, **kwargs)
                    
                    # 결과에서 토큰 수 추정
                    output_text = ""
                    model_name = "unknown"
                    
                    if hasattr(result, 'text'):
                        output_text = result.text or ""
                    elif isinstance(result, str):
                        output_text = result
                    
                    # 모델명 추출 (self에서 확인)
                    if hasattr(args[0], 'model_name'):
                        model_name = args[0].model_name
                    elif hasattr(args[0], 'gemini_config'):
                        model_name = args[0].gemini_config.model_name
                    
                    output_tokens = self.estimate_tokens(output_text)
                    total_tokens = input_tokens + output_tokens
                    processing_time = (time.time() - start_time) * 1000
                    
                    # 비용 계산
                    cost_usd, cost_krw = self.calculate_cost(model_name, input_tokens, output_tokens)
                    
                    # 로그 기록
                    log_entry = APICallLog(
                        timestamp=datetime.now().isoformat(),
                        task_id=task_id,
                        agent_name=agent_name,
                        function_name=function_name,
                        model_name=model_name,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        estimated_cost_usd=cost_usd,
                        estimated_cost_krw=cost_krw,
                        processing_time_ms=processing_time,
                        success=True,
                        context={
                            "input_length": len(input_text),
                            "output_length": len(output_text)
                        }
                    )
                    
                    self.log_api_call(log_entry)
                    
                    return result
                    
                except Exception as e:
                    # 에러 로깅
                    processing_time = (time.time() - start_time) * 1000
                    
                    log_entry = APICallLog(
                        timestamp=datetime.now().isoformat(),
                        task_id=task_id,
                        agent_name=agent_name,
                        function_name=function_name,
                        model_name="unknown",
                        input_tokens=input_tokens,
                        output_tokens=0,
                        total_tokens=input_tokens,
                        estimated_cost_usd=0.0,
                        estimated_cost_krw=0.0,
                        processing_time_ms=processing_time,
                        success=False,
                        error_message=str(e)
                    )
                    
                    self.log_api_call(log_entry)
                    
                    raise
                    
            return wrapper
        return decorator

    async def get_cost_summary(self) -> Dict[str, Any]:
        """비용 요약 정보 반환"""
        import datetime
        
        now = datetime.datetime.now()
        today = now.date()
        this_hour = now.replace(minute=0, second=0, microsecond=0)
        
        # 로그 파일 읽기
        logs = []
        if os.path.exists(self.log_file_path):
            try:
                with open(self.log_file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            logs.append(json.loads(line.strip()))
            except Exception as e:
                logger.warning(f"Failed to read cost logs: {e}")
        
        # 오늘 비용 계산
        today_cost = 0.0
        today_calls = 0
        
        # 이번 시간 비용 계산
        hour_cost = 0.0
        hour_calls = 0
        
        # 총 비용 계산
        total_cost = 0.0
        total_calls = len(logs)
        
        for log in logs:
            cost = log.get('estimated_cost_usd', 0.0)
            total_cost += cost
            
            # 날짜 파싱
            try:
                log_time = datetime.datetime.fromisoformat(log['timestamp'].replace('Z', '+00:00'))
                log_date = log_time.date()
                log_hour = log_time.replace(minute=0, second=0, microsecond=0, tzinfo=None)
                
                if log_date == today:
                    today_cost += cost
                    today_calls += 1
                    
                    if log_hour == this_hour:
                        hour_cost += cost
                        hour_calls += 1
            except Exception:
                continue
        
        return {
            "summary": {
                "total_cost": round(total_cost, 6),
                "total_calls": total_calls,
                "today_cost": round(today_cost, 6),
                "today_calls": today_calls,
                "current_hour_cost": round(hour_cost, 6),
                "current_hour_calls": hour_calls
            },
            "period": {
                "today": str(today),
                "current_hour": this_hour.strftime("%Y-%m-%d %H:00")
            },
            "last_updated": now.isoformat()
        }
    
    async def get_cost_logs(self, task_id: str = None, hours: int = 24, agent: str = None) -> List[Dict[str, Any]]:
        """비용 로그 조회"""
        import datetime
        
        logs = []
        if not os.path.exists(self.log_file_path):
            return logs
        
        cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=hours)
        
        try:
            with open(self.log_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        log = json.loads(line.strip())
                        
                        # 시간 필터링
                        try:
                            log_time = datetime.datetime.fromisoformat(log['timestamp'].replace('Z', '+00:00'))
                            if log_time < cutoff_time:
                                continue
                        except Exception:
                            continue
                        
                        # task_id 필터링
                        if task_id and log.get('task_id') != task_id:
                            continue
                        
                        # agent 필터링
                        if agent and log.get('agent_name') != agent:
                            continue
                        
                        logs.append(log)
        except Exception as e:
            logger.warning(f"Failed to read cost logs: {e}")
        
        # 최신순으로 정렬
        logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return logs
    
    async def get_alerts_status(self) -> Dict[str, Any]:
        """알림 상태 조회"""
        summary = await self.get_cost_summary()
        
        # 기본 임계치 (하드코딩, 실제로는 설정 파일이나 DB에서 가져와야 함)
        thresholds = {
            "daily_limit": 10.0,  # USD
            "hourly_limit": 2.0,  # USD
            "api_call_limit": 1000,
            "enabled": True
        }
        
        current_status = summary["summary"]
        
        alerts = []
        
        if thresholds["enabled"]:
            # 일일 한도 체크
            if current_status["today_cost"] >= thresholds["daily_limit"]:
                alerts.append({
                    "type": "DAILY_COST_EXCEEDED",
                    "message": f"Daily cost limit exceeded: ${current_status['today_cost']:.4f} >= ${thresholds['daily_limit']}",
                    "severity": "CRITICAL"
                })
            elif current_status["today_cost"] >= thresholds["daily_limit"] * 0.8:
                alerts.append({
                    "type": "DAILY_COST_WARNING",
                    "message": f"Daily cost approaching limit: ${current_status['today_cost']:.4f} / ${thresholds['daily_limit']}",
                    "severity": "WARNING"
                })
            
            # 시간당 한도 체크
            if current_status["current_hour_cost"] >= thresholds["hourly_limit"]:
                alerts.append({
                    "type": "HOURLY_COST_EXCEEDED",
                    "message": f"Hourly cost limit exceeded: ${current_status['current_hour_cost']:.4f} >= ${thresholds['hourly_limit']}",
                    "severity": "CRITICAL"
                })
            
            # API 호출 수 체크
            if current_status["today_calls"] >= thresholds["api_call_limit"]:
                alerts.append({
                    "type": "API_CALL_LIMIT_EXCEEDED",
                    "message": f"API call limit exceeded: {current_status['today_calls']} >= {thresholds['api_call_limit']}",
                    "severity": "CRITICAL"
                })
        
        return {
            "alerts": alerts,
            "thresholds": thresholds,
            "current_status": current_status,
            "alert_count": len(alerts)
        }
    
    async def set_alert_thresholds(self, daily_limit: float, hourly_limit: float, 
                                   api_call_limit: int, enabled: bool):
        """알림 임계치 설정 (현재는 로그만 출력, 실제로는 설정 저장 필요)"""
        logger.info(f"Alert thresholds updated: daily=${daily_limit}, hourly=${hourly_limit}, "
                   f"api_calls={api_call_limit}, enabled={enabled}")
        
        # 실제 구현에서는 설정을 파일이나 DB에 저장해야 함
        # 현재는 로깅만 수행

# 전역 인스턴스
_api_tracker = None

def get_api_tracker() -> GeminiAPITracker:
    """API 추적기 싱글톤 인스턴스 반환"""
    global _api_tracker
    if _api_tracker is None:
        _api_tracker = GeminiAPITracker()
    return _api_tracker