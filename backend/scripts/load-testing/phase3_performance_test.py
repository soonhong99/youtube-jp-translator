#!/usr/bin/env python3
"""
Phase 3 성능 테스트 스크립트
8초/30초 성능 목표 검증
"""

import asyncio
import json
import logging
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Tuple
import httpx
import random
import argparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Phase3PerformanceTest:
    """Phase 3 성능 테스트"""

    def __init__(self):
        # 서비스 URL
        self.api_gateway_url = "http://localhost:8080"
        self.intelligent_buffering_url = "http://localhost:8008"
        self.api_optimization_url = "http://localhost:8009"

        # 테스트 설정
        self.config = {
            'concurrent_requests': 10,      # 동시 요청 수
            'test_duration': 300,          # 테스트 지속 시간 (초)
            'target_first_result': 8.0,    # 첫 결과 목표 시간 (초)
            'target_completion': 30.0,     # 전체 완료 목표 시간 (초)
            'target_throughput': 100,      # 목표 처리량 (요청/분)
            'acceptable_error_rate': 0.05, # 허용 오류율 (5%)
        }

        # 테스트 데이터
        self.test_texts = [
            "こんにちは、今日は良い天気ですね。",
            "会議の時間を変更する必要があります。",
            "新しいプロジェクトについて話し合いましょう。",
            "システムの性能が向上しています。",
            "データ分析の結果を共有します。",
            "お疲れ様でした。また明日お会いしましょう。",
            "技術的な問題が発生しています。",
            "顧客からの要望を検討しています。",
            "チームワークが重要だと思います。",
            "品質管理を強化する必要があります。"
        ]

        # 결과 수집
        self.results = {
            'first_results': [],           # 첫 결과까지 시간
            'completion_times': [],        # 전체 완료 시간
            'throughput': 0.0,            # 처리량
            'error_count': 0,             # 오류 수
            'total_requests': 0,          # 전체 요청 수
            'cache_hit_rate': 0.0,        # 캐시 히트율
            'model_usage': {},            # 모델 사용 통계
            'cost_analysis': {},          # 비용 분석
        }

    async def run_comprehensive_test(self) -> Dict[str, Any]:
        """종합 성능 테스트 실행"""
        logger.info("🚀 Phase 3 종합 성능 테스트 시작")

        start_time = time.time()

        try:
            # 1. 사전 워밍업
            await self._warmup_services()

            # 2. 지능형 버퍼링 테스트
            buffering_results = await self._test_intelligent_buffering()

            # 3. API 최적화 테스트
            optimization_results = await self._test_api_optimization()

            # 4. 통합 워크플로우 테스트
            workflow_results = await self._test_integrated_workflow()

            # 5. 부하 테스트
            load_test_results = await self._run_load_test()

            # 6. 결과 분석
            analysis = await self._analyze_results()

            total_time = time.time() - start_time

            return {
                'test_duration': total_time,
                'buffering_results': buffering_results,
                'optimization_results': optimization_results,
                'workflow_results': workflow_results,
                'load_test_results': load_test_results,
                'analysis': analysis,
                'target_achievement': self._check_target_achievement()
            }

        except Exception as e:
            logger.error(f"❌ 성능 테스트 실패: {e}")
            raise

    async def _warmup_services(self):
        """서비스 워밍업"""
        logger.info("🔥 서비스 워밍업 중...")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 헬스체크
            services = [
                (self.api_gateway_url, "/health"),
                (self.intelligent_buffering_url, "/health"),
                (self.api_optimization_url, "/health")
            ]

            for base_url, endpoint in services:
                try:
                    response = await client.get(f"{base_url}{endpoint}")
                    if response.status_code == 200:
                        logger.info(f"✅ {base_url} 준비 완료")
                    else:
                        logger.warning(f"⚠️ {base_url} 상태 이상: {response.status_code}")
                except Exception as e:
                    logger.error(f"❌ {base_url} 연결 실패: {e}")

            # 워밍업 요청
            for i in range(5):
                test_text = random.choice(self.test_texts)
                try:
                    # 지능형 버퍼링 워밍업
                    await client.post(f"{self.intelligent_buffering_url}/buffer/add", json={
                        'task_id': f'warmup_{i}',
                        'text': test_text,
                        'start_time': 0.0,
                        'end_time': 2.0,
                        'chunk_id': f'chunk_{i}',
                        'confidence': 0.9
                    })

                    # API 최적화 워밍업
                    await client.post(f"{self.api_optimization_url}/translate", json={
                        'task_id': f'warmup_translate_{i}',
                        'source_text': test_text,
                        'target_language': 'ko',
                        'priority': 'normal'
                    })

                except Exception as e:
                    logger.debug(f"워밍업 요청 실패 (정상): {e}")

            await asyncio.sleep(2)  # 워밍업 완료 대기

    async def _test_intelligent_buffering(self) -> Dict[str, Any]:
        """지능형 버퍼링 테스트"""
        logger.info("🧠 지능형 버퍼링 테스트 시작")

        results = {
            'trigger_times': [],
            'completion_scores': [],
            'buffer_efficiencies': [],
            'trigger_reasons': {}
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(20):  # 20개 테스트
                task_id = f'buffering_test_{i}'
                test_text = random.choice(self.test_texts)

                start_time = time.time()

                try:
                    # 청크 시뮬레이션 (3-5개 청크)
                    chunk_count = random.randint(3, 5)
                    triggered = False

                    for chunk_idx in range(chunk_count):
                        chunk_text = test_text[:len(test_text) * (chunk_idx + 1) // chunk_count]

                        response = await client.post(f"{self.intelligent_buffering_url}/buffer/add", json={
                            'task_id': task_id,
                            'text': chunk_text,
                            'start_time': chunk_idx * 2.0,
                            'end_time': (chunk_idx + 1) * 2.0,
                            'chunk_id': f'chunk_{chunk_idx}',
                            'confidence': random.uniform(0.8, 0.95)
                        })

                        if response.status_code == 200:
                            result = response.json()
                            if result.get('should_trigger', False) and not triggered:
                                trigger_time = time.time() - start_time
                                results['trigger_times'].append(trigger_time)
                                results['completion_scores'].append(result.get('confidence', 0.0))

                                trigger_reason = result.get('trigger_reason', 'unknown')
                                results['trigger_reasons'][trigger_reason] = results['trigger_reasons'].get(trigger_reason, 0) + 1

                                triggered = True

                        await asyncio.sleep(0.5)  # 청크 간 간격

                    if not triggered:
                        # 강제 트리거
                        await client.post(f"{self.intelligent_buffering_url}/buffer/force-trigger", json={
                            'task_id': task_id,
                            'reason': 'test_timeout'
                        })
                        results['trigger_times'].append(time.time() - start_time)

                except Exception as e:
                    logger.error(f"❌ 버퍼링 테스트 실패: {task_id} - {e}")

        # 결과 분석
        if results['trigger_times']:
            results['avg_trigger_time'] = statistics.mean(results['trigger_times'])
            results['min_trigger_time'] = min(results['trigger_times'])
            results['max_trigger_time'] = max(results['trigger_times'])
            results['trigger_time_p95'] = statistics.quantiles(results['trigger_times'], n=20)[18]  # 95th percentile

        return results

    async def _test_api_optimization(self) -> Dict[str, Any]:
        """API 최적화 테스트"""
        logger.info("🚀 API 최적화 테스트 시작")

        results = {
            'translation_times': [],
            'cache_hits': 0,
            'cache_misses': 0,
            'model_usage': {},
            'costs': [],
            'quality_scores': []
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(30):  # 30개 테스트 (캐시 효과 확인)
                task_id = f'optimization_test_{i}'
                test_text = random.choice(self.test_texts)

                start_time = time.time()

                try:
                    response = await client.post(f"{self.api_optimization_url}/translate", json={
                        'task_id': task_id,
                        'source_text': test_text,
                        'target_language': 'ko',
                        'priority': random.choice(['low', 'normal', 'high']),
                        'max_latency': random.uniform(5.0, 15.0),
                        'min_quality': random.uniform(0.7, 0.9)
                    })

                    translation_time = time.time() - start_time

                    if response.status_code == 200:
                        result = response.json()
                        results['translation_times'].append(translation_time)

                        if result.get('cache_hit', False):
                            results['cache_hits'] += 1
                        else:
                            results['cache_misses'] += 1

                        model_used = result.get('model_used', 'unknown')
                        results['model_usage'][model_used] = results['model_usage'].get(model_used, 0) + 1

                        results['costs'].append(result.get('cost', 0.0))
                        results['quality_scores'].append(result.get('quality_score', 0.0))

                    else:
                        logger.warning(f"⚠️ 번역 요청 실패: {response.status_code}")

                except Exception as e:
                    logger.error(f"❌ 최적화 테스트 실패: {task_id} - {e}")

                await asyncio.sleep(0.2)  # 요청 간 간격

        # 결과 분석
        if results['translation_times']:
            results['avg_translation_time'] = statistics.mean(results['translation_times'])
            results['cache_hit_rate'] = results['cache_hits'] / (results['cache_hits'] + results['cache_misses'])
            results['total_cost'] = sum(results['costs'])
            results['avg_quality'] = statistics.mean(results['quality_scores'])

        return results

    async def _test_integrated_workflow(self) -> Dict[str, Any]:
        """통합 워크플로우 테스트"""
        logger.info("🔄 통합 워크플로우 테스트 시작")

        results = {
            'end_to_end_times': [],
            'first_result_times': [],
            'success_count': 0,
            'error_count': 0
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            # 동시 요청 테스트
            tasks = []
            for i in range(15):
                task = self._run_integrated_workflow_test(client, f'workflow_test_{i}')
                tasks.append(task)

            # 결과 수집
            completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)

            for result in completed_tasks:
                if isinstance(result, Exception):
                    results['error_count'] += 1
                    logger.error(f"워크플로우 테스트 오류: {result}")
                elif result:
                    results['success_count'] += 1
                    results['end_to_end_times'].append(result['total_time'])
                    if 'first_result_time' in result:
                        results['first_result_times'].append(result['first_result_time'])

        # 결과 분석
        if results['end_to_end_times']:
            results['avg_end_to_end_time'] = statistics.mean(results['end_to_end_times'])
            results['p95_end_to_end_time'] = statistics.quantiles(results['end_to_end_times'], n=20)[18]

        if results['first_result_times']:
            results['avg_first_result_time'] = statistics.mean(results['first_result_times'])
            results['p95_first_result_time'] = statistics.quantiles(results['first_result_times'], n=20)[18] if len(results['first_result_times']) >= 20 else max(results['first_result_times'])

        results['success_rate'] = results['success_count'] / (results['success_count'] + results['error_count'])

        return results

    async def _run_integrated_workflow_test(self, client: httpx.AsyncClient, task_id: str) -> Dict[str, Any]:
        """통합 워크플로우 단일 테스트"""
        start_time = time.time()
        first_result_time = None
        test_text = random.choice(self.test_texts)

        try:
            # 1. 지능형 버퍼링 단계
            chunk_count = random.randint(3, 5)

            for chunk_idx in range(chunk_count):
                chunk_text = test_text[:len(test_text) * (chunk_idx + 1) // chunk_count]

                response = await client.post(f"{self.intelligent_buffering_url}/buffer/add", json={
                    'task_id': task_id,
                    'text': chunk_text,
                    'start_time': chunk_idx * 2.0,
                    'end_time': (chunk_idx + 1) * 2.0,
                    'chunk_id': f'chunk_{chunk_idx}',
                    'confidence': random.uniform(0.8, 0.95)
                })

                if response.status_code == 200:
                    result = response.json()
                    if result.get('should_trigger', False) and first_result_time is None:
                        first_result_time = time.time() - start_time

                await asyncio.sleep(0.5)

            # 2. 번역 처리 (시뮬레이션)
            await client.post(f"{self.api_optimization_url}/translate", json={
                'task_id': f'{task_id}_translate',
                'source_text': test_text,
                'target_language': 'ko',
                'priority': 'normal'
            })

            total_time = time.time() - start_time

            return {
                'task_id': task_id,
                'total_time': total_time,
                'first_result_time': first_result_time or total_time,
                'success': True
            }

        except Exception as e:
            logger.error(f"❌ 통합 워크플로우 테스트 실패: {task_id} - {e}")
            return {'task_id': task_id, 'success': False, 'error': str(e)}

    async def _run_load_test(self) -> Dict[str, Any]:
        """부하 테스트"""
        logger.info("⚡ 부하 테스트 시작")

        results = {
            'requests_per_second': [],
            'response_times': [],
            'error_rates': [],
            'resource_usage': []
        }

        # 점진적 부하 증가
        load_levels = [5, 10, 20, 30, 50]  # 동시 요청 수

        async with httpx.AsyncClient(timeout=30.0) as client:
            for load_level in load_levels:
                logger.info(f"📈 부하 레벨 {load_level} 테스트 중...")

                start_time = time.time()
                tasks = []

                # 동시 요청 생성
                for i in range(load_level):
                    task = self._single_load_test_request(client, f'load_{load_level}_{i}')
                    tasks.append(task)

                # 결과 수집
                completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)

                test_duration = time.time() - start_time
                success_count = sum(1 for result in completed_tasks if not isinstance(result, Exception))
                error_count = len(completed_tasks) - success_count

                # 메트릭 계산
                rps = success_count / test_duration if test_duration > 0 else 0
                error_rate = error_count / len(completed_tasks) if completed_tasks else 0

                response_times = [
                    result['response_time'] for result in completed_tasks
                    if isinstance(result, dict) and 'response_time' in result
                ]

                results['requests_per_second'].append(rps)
                results['error_rates'].append(error_rate)
                if response_times:
                    results['response_times'].append(statistics.mean(response_times))

                logger.info(f"📊 부하 레벨 {load_level}: RPS={rps:.2f}, 오류율={error_rate:.2%}")

                await asyncio.sleep(2)  # 부하 레벨 간 휴식

        return results

    async def _single_load_test_request(self, client: httpx.AsyncClient, task_id: str) -> Dict[str, Any]:
        """단일 부하 테스트 요청"""
        start_time = time.time()

        try:
            test_text = random.choice(self.test_texts)

            response = await client.post(f"{self.api_optimization_url}/translate", json={
                'task_id': task_id,
                'source_text': test_text,
                'target_language': 'ko',
                'priority': 'normal'
            })

            response_time = time.time() - start_time

            return {
                'task_id': task_id,
                'response_time': response_time,
                'success': response.status_code == 200,
                'status_code': response.status_code
            }

        except Exception as e:
            return {
                'task_id': task_id,
                'response_time': time.time() - start_time,
                'success': False,
                'error': str(e)
            }

    async def _analyze_results(self) -> Dict[str, Any]:
        """결과 종합 분석"""
        logger.info("📊 결과 분석 중...")

        analysis = {}

        try:
            # 서비스 메트릭 수집
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 지능형 버퍼링 메트릭
                try:
                    response = await client.get(f"{self.intelligent_buffering_url}/metrics")
                    if response.status_code == 200:
                        analysis['buffering_metrics'] = response.json()
                except Exception as e:
                    logger.debug(f"버퍼링 메트릭 수집 실패: {e}")

                # API 최적화 메트릭
                try:
                    response = await client.get(f"{self.api_optimization_url}/metrics")
                    if response.status_code == 200:
                        analysis['optimization_metrics'] = response.json()
                except Exception as e:
                    logger.debug(f"최적화 메트릭 수집 실패: {e}")

                # 비용 분석
                try:
                    response = await client.get(f"{self.api_optimization_url}/cost/analysis")
                    if response.status_code == 200:
                        analysis['cost_analysis'] = response.json()
                except Exception as e:
                    logger.debug(f"비용 분석 수집 실패: {e}")

                # 캐시 통계
                try:
                    response = await client.get(f"{self.api_optimization_url}/cache/stats")
                    if response.status_code == 200:
                        analysis['cache_stats'] = response.json()
                except Exception as e:
                    logger.debug(f"캐시 통계 수집 실패: {e}")

        except Exception as e:
            logger.error(f"❌ 메트릭 수집 실패: {e}")

        return analysis

    def _check_target_achievement(self) -> Dict[str, Any]:
        """목표 달성도 확인"""
        achievement = {
            'first_result_target': self.config['target_first_result'],
            'completion_target': self.config['target_completion'],
            'throughput_target': self.config['target_throughput'],
            'error_rate_target': self.config['acceptable_error_rate'],
        }

        # 실제 달성도는 테스트 결과에서 계산
        # 여기서는 구조만 제공

        return achievement

    async def run_quick_test(self) -> Dict[str, Any]:
        """빠른 테스트 (개발용)"""
        logger.info("⚡ 빠른 테스트 시작")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 단순 응답 테스트
            services = [
                (self.intelligent_buffering_url, "/health"),
                (self.api_optimization_url, "/health")
            ]

            results = {}
            for base_url, endpoint in services:
                start_time = time.time()
                try:
                    response = await client.get(f"{base_url}{endpoint}")
                    response_time = time.time() - start_time

                    results[base_url] = {
                        'status_code': response.status_code,
                        'response_time': response_time,
                        'healthy': response.status_code == 200
                    }
                except Exception as e:
                    results[base_url] = {
                        'error': str(e),
                        'healthy': False
                    }

            return results

def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description='Phase 3 Performance Test')
    parser.add_argument('--mode', choices=['quick', 'full'], default='quick',
                       help='Test mode (quick or full)')
    parser.add_argument('--output', type=str, help='Output file for results')

    args = parser.parse_args()

    # 테스트 실행
    tester = Phase3PerformanceTest()

    async def run_test():
        if args.mode == 'quick':
            return await tester.run_quick_test()
        else:
            return await tester.run_comprehensive_test()

    # 결과 실행
    results = asyncio.run(run_test())

    # 결과 출력
    print(json.dumps(results, indent=2, ensure_ascii=False))

    # 파일 저장
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"결과를 {args.output}에 저장했습니다.")

if __name__ == "__main__":
    main()