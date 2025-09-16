"""
비용 최적화 시스템 - API 비용 최소화 및 모델 선택 최적화
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
from collections import defaultdict, deque
import statistics
import numpy as np

logger = logging.getLogger(__name__)

class ModelType(Enum):
    """모델 타입"""
    GEMINI_FLASH = "gemini-1.5-flash"
    GEMINI_PRO = "gemini-1.5-pro"
    GEMINI_PRO_2 = "gemini-2.5-pro"
    CLAUDE_HAIKU = "claude-3-haiku"
    OPENAI_MINI = "gpt-4o-mini"

@dataclass
class ModelConfig:
    """모델 설정"""
    model_type: ModelType
    cost_per_1k_tokens: float       # 1K 토큰당 비용 (USD)
    max_tokens_per_minute: int      # 분당 최대 토큰
    max_requests_per_minute: int    # 분당 최대 요청
    average_latency: float          # 평균 지연시간 (초)
    quality_score: float            # 품질 점수 (0.0-1.0)
    reliability_score: float        # 신뢰도 점수 (0.0-1.0)
    availability: bool = True       # 사용 가능 여부

@dataclass
class CostAnalysis:
    """비용 분석"""
    total_cost: float = 0.0
    token_count: int = 0
    request_count: int = 0
    cost_per_request: float = 0.0
    cost_efficiency: float = 0.0    # 품질/비용 비율
    time_period: float = 0.0        # 분석 기간 (초)

@dataclass
class UsageRecord:
    """사용 기록"""
    model_type: ModelType
    token_count: int
    cost: float
    latency: float
    success: bool
    quality_score: float
    timestamp: float = field(default_factory=time.time)

class CostOptimizer:
    """비용 최적화 시스템"""

    def __init__(self, redis_client=None):
        self.redis_client = redis_client

        # 모델 설정 (2024년 12월 기준 가격)
        self.model_configs = {
            ModelType.GEMINI_FLASH: ModelConfig(
                model_type=ModelType.GEMINI_FLASH,
                cost_per_1k_tokens=0.000075,    # $0.000075/1K tokens
                max_tokens_per_minute=1000000,   # 1M tokens/min
                max_requests_per_minute=15,      # 15 requests/min (free tier)
                average_latency=1.5,
                quality_score=0.85,
                reliability_score=0.95
            ),
            ModelType.GEMINI_PRO: ModelConfig(
                model_type=ModelType.GEMINI_PRO,
                cost_per_1k_tokens=0.00125,     # $0.00125/1K tokens
                max_tokens_per_minute=1000000,
                max_requests_per_minute=15,
                average_latency=2.5,
                quality_score=0.92,
                reliability_score=0.93
            ),
            ModelType.GEMINI_PRO_2: ModelConfig(
                model_type=ModelType.GEMINI_PRO_2,
                cost_per_1k_tokens=0.00375,     # $0.00375/1K tokens
                max_tokens_per_minute=1000000,
                max_requests_per_minute=10,
                average_latency=3.0,
                quality_score=0.95,
                reliability_score=0.90
            ),
            ModelType.CLAUDE_HAIKU: ModelConfig(
                model_type=ModelType.CLAUDE_HAIKU,
                cost_per_1k_tokens=0.00025,     # $0.00025/1K tokens
                max_tokens_per_minute=100000,
                max_requests_per_minute=50,
                average_latency=1.8,
                quality_score=0.88,
                reliability_score=0.97
            ),
            ModelType.OPENAI_MINI: ModelConfig(
                model_type=ModelType.OPENAI_MINI,
                cost_per_1k_tokens=0.00015,     # $0.00015/1K tokens
                max_tokens_per_minute=200000,
                max_requests_per_minute=30,
                average_latency=2.0,
                quality_score=0.86,
                reliability_score=0.95
            )
        }

        # 사용 기록
        self.usage_history: deque = deque(maxlen=10000)
        self.model_usage: Dict[ModelType, deque] = {
            model_type: deque(maxlen=1000) for model_type in ModelType
        }

        # 비용 추적
        self.daily_costs: Dict[str, CostAnalysis] = {}  # date -> CostAnalysis
        self.hourly_usage: Dict[ModelType, List[int]] = defaultdict(lambda: [0] * 24)

        # 설정
        self.config = {
            'daily_budget': 10.0,              # 일일 예산 (USD)
            'cost_optimization_weight': 0.4,   # 비용 최적화 가중치
            'quality_threshold': 0.8,          # 최소 품질 임계값
            'latency_threshold': 5.0,          # 최대 지연시간 (초)
            'emergency_fallback': True,        # 비상 대체 모델 사용
            'budget_alert_threshold': 0.8,     # 예산 경고 임계값 (80%)
        }

        # 최적화 파라미터
        self.optimization_params = {
            'cost_efficiency_weight': 0.5,     # 비용 효율성 가중치
            'latency_weight': 0.3,             # 지연시간 가중치
            'quality_weight': 0.2,             # 품질 가중치
            'reliability_bonus': 0.1,          # 신뢰도 보너스
        }

        logger.info("✅ CostOptimizer 초기화 완료")

    async def select_optimal_model(self, task_requirements: Dict[str, Any]) -> Tuple[ModelType, float]:
        """최적 모델 선택"""
        try:
            # 요구사항 파싱
            max_cost = task_requirements.get('max_cost', float('inf'))
            min_quality = task_requirements.get('min_quality', self.config['quality_threshold'])
            max_latency = task_requirements.get('max_latency', self.config['latency_threshold'])
            token_count = task_requirements.get('estimated_tokens', 1000)
            priority = task_requirements.get('priority', 'normal')  # low, normal, high, critical

            # 현재 사용량 확인
            current_usage = await self._get_current_usage()

            # 각 모델 평가
            model_scores = {}
            for model_type, config in self.model_configs.items():
                if not config.availability:
                    continue

                # 사용량 제한 확인
                if not await self._check_usage_limits(model_type, token_count):
                    continue

                # 요구사항 충족 확인
                estimated_cost = self._estimate_cost(model_type, token_count)
                if estimated_cost > max_cost:
                    continue

                if config.quality_score < min_quality:
                    continue

                if config.average_latency > max_latency:
                    continue

                # 모델 점수 계산
                score = await self._calculate_model_score(
                    model_type, config, task_requirements, current_usage
                )
                model_scores[model_type] = score

            if not model_scores:
                # 요구사항을 만족하는 모델이 없는 경우 대체 방안
                return await self._select_fallback_model(task_requirements)

            # 최고 점수 모델 선택
            best_model = max(model_scores.keys(), key=model_scores.get)
            confidence = model_scores[best_model]

            logger.debug(f"🎯 최적 모델 선택: {best_model.value} (신뢰도: {confidence:.2f})")
            return best_model, confidence

        except Exception as e:
            logger.error(f"❌ 최적 모델 선택 실패: {e}")
            return ModelType.GEMINI_FLASH, 0.5  # 기본 모델

    async def _calculate_model_score(self, model_type: ModelType, config: ModelConfig,
                                   requirements: Dict[str, Any], current_usage: Dict) -> float:
        """모델 점수 계산"""
        try:
            token_count = requirements.get('estimated_tokens', 1000)
            priority = requirements.get('priority', 'normal')

            # 기본 점수 계산
            cost_score = self._calculate_cost_score(model_type, token_count)
            latency_score = self._calculate_latency_score(config.average_latency)
            quality_score = config.quality_score
            reliability_score = config.reliability_score

            # 우선순위별 가중치 조정
            weights = self.optimization_params.copy()
            if priority == 'critical':
                weights['latency_weight'] *= 2.0
                weights['quality_weight'] *= 1.5
            elif priority == 'low':
                weights['cost_efficiency_weight'] *= 1.5

            # 종합 점수 계산
            total_score = (
                cost_score * weights['cost_efficiency_weight'] +
                latency_score * weights['latency_weight'] +
                quality_score * weights['quality_weight'] +
                reliability_score * weights['reliability_bonus']
            )

            # 사용량 기반 조정
            usage_factor = await self._get_usage_factor(model_type, current_usage)
            adjusted_score = total_score * usage_factor

            # 일일 예산 고려
            daily_cost_factor = await self._get_daily_cost_factor()
            final_score = adjusted_score * daily_cost_factor

            return min(1.0, max(0.0, final_score))

        except Exception as e:
            logger.error(f"❌ 모델 점수 계산 실패: {model_type} - {e}")
            return 0.0

    def _calculate_cost_score(self, model_type: ModelType, token_count: int) -> float:
        """비용 점수 계산 (낮은 비용일수록 높은 점수)"""
        try:
            config = self.model_configs[model_type]
            cost = self._estimate_cost(model_type, token_count)

            # 모든 모델의 비용과 비교하여 상대적 점수 계산
            all_costs = [
                self._estimate_cost(mt, token_count)
                for mt in ModelType if self.model_configs[mt].availability
            ]

            if not all_costs:
                return 0.5

            min_cost = min(all_costs)
            max_cost = max(all_costs)

            if max_cost == min_cost:
                return 1.0

            # 역정규화 (낮은 비용 = 높은 점수)
            score = 1.0 - (cost - min_cost) / (max_cost - min_cost)
            return max(0.0, min(1.0, score))

        except Exception:
            return 0.5

    def _calculate_latency_score(self, latency: float) -> float:
        """지연시간 점수 계산 (낮은 지연시간일수록 높은 점수)"""
        try:
            max_acceptable_latency = self.config['latency_threshold']

            if latency <= 1.0:
                return 1.0
            elif latency >= max_acceptable_latency:
                return 0.1
            else:
                # 선형 감소
                score = 1.0 - (latency - 1.0) / (max_acceptable_latency - 1.0)
                return max(0.1, min(1.0, score))

        except Exception:
            return 0.5

    async def _get_usage_factor(self, model_type: ModelType, current_usage: Dict) -> float:
        """사용량 기반 조정 계수"""
        try:
            config = self.model_configs[model_type]
            current_requests = current_usage.get(model_type, {}).get('requests', 0)
            current_tokens = current_usage.get(model_type, {}).get('tokens', 0)

            # 사용량 비율 계산
            request_ratio = current_requests / config.max_requests_per_minute
            token_ratio = current_tokens / config.max_tokens_per_minute

            # 높은 사용량일수록 점수 감소
            max_usage_ratio = max(request_ratio, token_ratio)

            if max_usage_ratio >= 0.9:
                return 0.1  # 거의 한계점
            elif max_usage_ratio >= 0.7:
                return 0.5  # 높은 사용량
            elif max_usage_ratio >= 0.5:
                return 0.8  # 중간 사용량
            else:
                return 1.0  # 낮은 사용량

        except Exception:
            return 1.0

    async def _get_daily_cost_factor(self) -> float:
        """일일 비용 기반 조정 계수"""
        try:
            today = time.strftime("%Y-%m-%d")
            if today in self.daily_costs:
                daily_cost = self.daily_costs[today].total_cost
                budget_ratio = daily_cost / self.config['daily_budget']

                if budget_ratio >= 1.0:
                    return 0.1  # 예산 초과
                elif budget_ratio >= self.config['budget_alert_threshold']:
                    return 0.5  # 예산 경고
                else:
                    return 1.0  # 정상
            else:
                return 1.0  # 오늘 첫 사용

        except Exception:
            return 1.0

    def _estimate_cost(self, model_type: ModelType, token_count: int) -> float:
        """비용 추정"""
        try:
            config = self.model_configs[model_type]
            return (token_count / 1000.0) * config.cost_per_1k_tokens

        except Exception:
            return 0.0

    async def _check_usage_limits(self, model_type: ModelType, token_count: int) -> bool:
        """사용량 제한 확인"""
        try:
            config = self.model_configs[model_type]
            current_usage = await self._get_current_usage()

            model_usage = current_usage.get(model_type, {'requests': 0, 'tokens': 0})

            # 요청 제한 확인
            if model_usage['requests'] >= config.max_requests_per_minute:
                return False

            # 토큰 제한 확인
            if model_usage['tokens'] + token_count > config.max_tokens_per_minute:
                return False

            return True

        except Exception as e:
            logger.error(f"❌ 사용량 제한 확인 실패: {model_type} - {e}")
            return False

    async def _get_current_usage(self) -> Dict[ModelType, Dict[str, int]]:
        """현재 사용량 조회 (분당)"""
        try:
            current_time = time.time()
            minute_ago = current_time - 60.0

            usage = {}
            for model_type in ModelType:
                model_records = self.model_usage[model_type]
                recent_records = [
                    record for record in model_records
                    if record.timestamp >= minute_ago
                ]

                usage[model_type] = {
                    'requests': len(recent_records),
                    'tokens': sum(record.token_count for record in recent_records)
                }

            return usage

        except Exception as e:
            logger.error(f"❌ 현재 사용량 조회 실패: {e}")
            return {}

    async def _select_fallback_model(self, requirements: Dict[str, Any]) -> Tuple[ModelType, float]:
        """대체 모델 선택"""
        try:
            logger.warning("⚠️ 요구사항 만족 모델 없음 - 대체 모델 선택")

            # 가장 저렴한 모델 우선
            cheapest_model = min(
                ModelType,
                key=lambda mt: self.model_configs[mt].cost_per_1k_tokens
                if self.model_configs[mt].availability else float('inf')
            )

            # 사용량 제한 확인
            if await self._check_usage_limits(cheapest_model, requirements.get('estimated_tokens', 1000)):
                return cheapest_model, 0.3

            # 사용 가능한 모델 중 선택
            for model_type in ModelType:
                if (self.model_configs[model_type].availability and
                    await self._check_usage_limits(model_type, requirements.get('estimated_tokens', 1000))):
                    return model_type, 0.2

            # 모든 모델이 제한된 경우 기본 모델
            return ModelType.GEMINI_FLASH, 0.1

        except Exception as e:
            logger.error(f"❌ 대체 모델 선택 실패: {e}")
            return ModelType.GEMINI_FLASH, 0.1

    def record_usage(self, model_type: ModelType, token_count: int, cost: float,
                    latency: float, success: bool, quality_score: float = 0.8):
        """사용 기록"""
        try:
            record = UsageRecord(
                model_type=model_type,
                token_count=token_count,
                cost=cost,
                latency=latency,
                success=success,
                quality_score=quality_score
            )

            # 전체 사용 기록
            self.usage_history.append(record)

            # 모델별 사용 기록
            self.model_usage[model_type].append(record)

            # 일일 비용 업데이트
            today = time.strftime("%Y-%m-%d")
            if today not in self.daily_costs:
                self.daily_costs[today] = CostAnalysis()

            daily_analysis = self.daily_costs[today]
            daily_analysis.total_cost += cost
            daily_analysis.token_count += token_count
            daily_analysis.request_count += 1

            if daily_analysis.request_count > 0:
                daily_analysis.cost_per_request = daily_analysis.total_cost / daily_analysis.request_count

            # 시간별 사용량 업데이트
            current_hour = int(time.strftime("%H"))
            self.hourly_usage[model_type][current_hour] += 1

            logger.debug(f"📊 사용 기록: {model_type.value} - 비용: ${cost:.4f}, 토큰: {token_count}")

        except Exception as e:
            logger.error(f"❌ 사용 기록 실패: {e}")

    async def get_cost_analysis(self, period: str = "today") -> Dict[str, Any]:
        """비용 분석 조회"""
        try:
            if period == "today":
                today = time.strftime("%Y-%m-%d")
                analysis = self.daily_costs.get(today, CostAnalysis())

                # 예산 대비 비율
                budget_usage = (analysis.total_cost / self.config['daily_budget'] * 100
                               if self.config['daily_budget'] > 0 else 0)

                return {
                    'period': period,
                    'total_cost': analysis.total_cost,
                    'total_requests': analysis.request_count,
                    'total_tokens': analysis.token_count,
                    'cost_per_request': analysis.cost_per_request,
                    'daily_budget': self.config['daily_budget'],
                    'budget_usage_percent': budget_usage,
                    'budget_remaining': max(0, self.config['daily_budget'] - analysis.total_cost)
                }

            elif period == "models":
                # 모델별 분석
                model_analysis = {}
                current_time = time.time()
                day_ago = current_time - 86400  # 24시간 전

                for model_type in ModelType:
                    records = [
                        record for record in self.model_usage[model_type]
                        if record.timestamp >= day_ago
                    ]

                    if records:
                        total_cost = sum(record.cost for record in records)
                        total_tokens = sum(record.token_count for record in records)
                        avg_latency = statistics.mean(record.latency for record in records)
                        success_rate = sum(1 for record in records if record.success) / len(records)
                        avg_quality = statistics.mean(record.quality_score for record in records)

                        model_analysis[model_type.value] = {
                            'total_cost': total_cost,
                            'total_requests': len(records),
                            'total_tokens': total_tokens,
                            'average_latency': avg_latency,
                            'success_rate': success_rate,
                            'average_quality': avg_quality,
                            'cost_efficiency': avg_quality / total_cost if total_cost > 0 else 0
                        }

                return model_analysis

            return {}

        except Exception as e:
            logger.error(f"❌ 비용 분석 조회 실패: {e}")
            return {}

    async def optimize_daily_budget(self, target_requests: int) -> Dict[str, Any]:
        """일일 예산 최적화"""
        try:
            # 현재까지의 사용 패턴 분석
            today = time.strftime("%Y-%m-%d")
            current_analysis = self.daily_costs.get(today, CostAnalysis())

            # 시간당 평균 비용 계산
            current_hour = int(time.strftime("%H"))
            if current_hour > 0:
                hourly_cost = current_analysis.total_cost / current_hour
            else:
                hourly_cost = 0

            # 하루 종료까지 예상 비용
            remaining_hours = 24 - current_hour
            projected_daily_cost = current_analysis.total_cost + (hourly_cost * remaining_hours)

            # 목표 요청 수 기반 비용 예측
            if current_analysis.request_count > 0:
                cost_per_request = current_analysis.cost_per_request
                target_cost = target_requests * cost_per_request
            else:
                # 평균 비용 사용
                avg_cost_per_request = 0.003  # $0.003 평균
                target_cost = target_requests * avg_cost_per_request

            # 최적화 제안
            recommendations = []

            if projected_daily_cost > self.config['daily_budget']:
                # 예산 초과 예상
                overage = projected_daily_cost - self.config['daily_budget']
                overage_percent = (overage / self.config['daily_budget']) * 100

                recommendations.append({
                    'type': 'budget_alert',
                    'message': f"예산 초과 예상: ${overage:.3f} ({overage_percent:.1f}%)",
                    'suggested_action': '저비용 모델 우선 사용'
                })

                # 저비용 모델 비율 증가 제안
                flash_ratio = 0.8  # Gemini Flash 80% 사용 권장
                recommendations.append({
                    'type': 'model_mix',
                    'gemini_flash_ratio': flash_ratio,
                    'estimated_savings': overage * 0.6
                })

            if target_cost > self.config['daily_budget']:
                # 목표 요청이 예산 초과
                max_affordable_requests = int(self.config['daily_budget'] / cost_per_request) if cost_per_request > 0 else target_requests
                recommendations.append({
                    'type': 'request_limit',
                    'max_affordable_requests': max_affordable_requests,
                    'budget_needed': target_cost
                })

            return {
                'current_cost': current_analysis.total_cost,
                'projected_daily_cost': projected_daily_cost,
                'target_cost': target_cost,
                'daily_budget': self.config['daily_budget'],
                'budget_utilization': (current_analysis.total_cost / self.config['daily_budget']) * 100,
                'recommendations': recommendations,
                'optimal_model_mix': await self._calculate_optimal_model_mix()
            }

        except Exception as e:
            logger.error(f"❌ 일일 예산 최적화 실패: {e}")
            return {}

    async def _calculate_optimal_model_mix(self) -> Dict[str, float]:
        """최적 모델 믹스 계산"""
        try:
            # 비용 효율성 기반 모델 믹스 계산
            model_efficiency = {}

            for model_type, config in self.model_configs.items():
                if config.availability:
                    # 효율성 = 품질 / 비용
                    efficiency = config.quality_score / config.cost_per_1k_tokens
                    model_efficiency[model_type.value] = efficiency

            # 정규화
            total_efficiency = sum(model_efficiency.values())
            optimal_mix = {
                model: efficiency / total_efficiency
                for model, efficiency in model_efficiency.items()
            }

            return optimal_mix

        except Exception:
            return {}

    async def get_budget_alerts(self) -> List[Dict[str, Any]]:
        """예산 경고 조회"""
        try:
            alerts = []
            today = time.strftime("%Y-%m-%d")
            current_analysis = self.daily_costs.get(today, CostAnalysis())

            budget_usage = current_analysis.total_cost / self.config['daily_budget']

            if budget_usage >= 1.0:
                alerts.append({
                    'level': 'critical',
                    'message': '일일 예산 초과',
                    'current_cost': current_analysis.total_cost,
                    'budget': self.config['daily_budget'],
                    'overage': current_analysis.total_cost - self.config['daily_budget']
                })
            elif budget_usage >= self.config['budget_alert_threshold']:
                alerts.append({
                    'level': 'warning',
                    'message': f'예산 {budget_usage*100:.1f}% 사용',
                    'current_cost': current_analysis.total_cost,
                    'budget': self.config['daily_budget'],
                    'remaining': self.config['daily_budget'] - current_analysis.total_cost
                })

            # 모델별 사용량 경고
            current_usage = await self._get_current_usage()
            for model_type, usage in current_usage.items():
                config = self.model_configs[model_type]
                request_ratio = usage['requests'] / config.max_requests_per_minute
                token_ratio = usage['tokens'] / config.max_tokens_per_minute

                if request_ratio >= 0.9 or token_ratio >= 0.9:
                    alerts.append({
                        'level': 'warning',
                        'message': f'{model_type.value} 사용량 한계 근접',
                        'request_usage': f'{request_ratio*100:.1f}%',
                        'token_usage': f'{token_ratio*100:.1f}%'
                    })

            return alerts

        except Exception as e:
            logger.error(f"❌ 예산 경고 조회 실패: {e}")
            return []