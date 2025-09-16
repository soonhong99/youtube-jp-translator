#!/usr/bin/env python3
"""
Phase 1 병렬 STT 처리 성능 테스트 스크립트
"""

import asyncio
import time
import json
import aiohttp
import logging
from typing import Dict, Any

# 로그 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PerformanceTest:
    def __init__(self):
        self.api_gateway_url = "http://localhost:8080"
        self.streaming_stt_url = "http://localhost:8007"

    async def test_youtube_extraction(self, youtube_url: str) -> Dict[str, Any]:
        """유튜브 오디오 추출 테스트"""
        logger.info(f"🎵 유튜브 오디오 추출 테스트 시작: {youtube_url}")

        start_time = time.time()

        async with aiohttp.ClientSession() as session:
            try:
                # 유튜브 오디오 추출 요청
                async with session.post(
                    f"{self.api_gateway_url}/api/extract",
                    json={"url": youtube_url}
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        end_time = time.time()

                        extraction_time = end_time - start_time
                        logger.info(f"✅ 오디오 추출 완료: {extraction_time:.2f}초")

                        return {
                            "success": True,
                            "extraction_time": extraction_time,
                            "audio_file": result.get("audio_file"),
                            "duration": result.get("duration", 0)
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ 오디오 추출 실패: {response.status} - {error_text}")
                        return {"success": False, "error": error_text}

            except Exception as e:
                logger.error(f"❌ 요청 실패: {e}")
                return {"success": False, "error": str(e)}

    async def test_streaming_stt_performance(self, audio_file: str) -> Dict[str, Any]:
        """Phase 1 병렬 STT 처리 성능 테스트"""
        logger.info(f"🚀 Phase 1 병렬 STT 처리 테스트 시작: {audio_file}")

        start_time = time.time()

        async with aiohttp.ClientSession() as session:
            try:
                # 스트리밍 STT 요청 (병렬 처리)
                request_data = {
                    "audio_file_path": audio_file,
                    "language": "ja",
                    "chunk_duration": 5.0,
                    "overlap_duration": 1.0,
                    "priority": 1
                }

                async with session.post(
                    f"{self.streaming_stt_url}/api/streaming-stt",
                    json=request_data
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        end_time = time.time()

                        total_time = end_time - start_time

                        # 성능 메트릭 계산
                        total_chunks = result.get("total_chunks", 0)
                        processed_chunks = result.get("processed_chunks", 0)
                        success_rate = (processed_chunks / total_chunks * 100) if total_chunks > 0 else 0

                        logger.info(f"✅ 병렬 STT 처리 완료: {total_time:.2f}초")
                        logger.info(f"📊 처리 결과: {processed_chunks}/{total_chunks}개 청크 ({success_rate:.1f}% 성공률)")

                        return {
                            "success": True,
                            "total_time": total_time,
                            "total_chunks": total_chunks,
                            "processed_chunks": processed_chunks,
                            "success_rate": success_rate,
                            "sentences": result.get("sentences", []),
                            "processing_mode": result.get("processing_mode", "unknown"),
                            "whisper_models_used": result.get("whisper_models", 1)
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ STT 처리 실패: {response.status} - {error_text}")
                        return {"success": False, "error": error_text}

            except Exception as e:
                logger.error(f"❌ STT 요청 실패: {e}")
                return {"success": False, "error": str(e)}

    async def run_performance_benchmark(self, youtube_url: str) -> Dict[str, Any]:
        """전체 성능 벤치마크 실행"""
        logger.info("🧪 Phase 1 성능 벤치마크 테스트 시작")

        benchmark_start = time.time()

        # 1. 유튜브 오디오 추출
        extraction_result = await self.test_youtube_extraction(youtube_url)
        if not extraction_result["success"]:
            return {
                "success": False,
                "error": "오디오 추출 실패",
                "details": extraction_result
            }

        audio_file = extraction_result["audio_file"]
        audio_duration = extraction_result["duration"]

        # 2. 병렬 STT 처리 테스트
        stt_result = await self.test_streaming_stt_performance(audio_file)
        if not stt_result["success"]:
            return {
                "success": False,
                "error": "STT 처리 실패",
                "extraction_result": extraction_result,
                "stt_result": stt_result
            }

        # 3. 성능 분석
        benchmark_end = time.time()
        total_benchmark_time = benchmark_end - benchmark_start

        # 성능 메트릭 계산
        stt_processing_time = stt_result["total_time"]
        chunks_per_second = stt_result["total_chunks"] / stt_processing_time if stt_processing_time > 0 else 0
        audio_processing_ratio = stt_processing_time / audio_duration if audio_duration > 0 else 0

        # 예상 순차 처리 시간 (기존 방식)
        estimated_sequential_time = stt_result["total_chunks"] * 2.3  # 청크당 2.3초

        # 성능 개선율 계산
        performance_improvement = ((estimated_sequential_time - stt_processing_time) / estimated_sequential_time * 100) if estimated_sequential_time > 0 else 0

        benchmark_result = {
            "success": True,
            "benchmark_summary": {
                "total_time": total_benchmark_time,
                "audio_duration": audio_duration,
                "extraction_time": extraction_result["extraction_time"],
                "stt_processing_time": stt_processing_time,
                "total_chunks": stt_result["total_chunks"],
                "processed_chunks": stt_result["processed_chunks"],
                "success_rate": stt_result["success_rate"],
                "whisper_models_used": stt_result["whisper_models_used"],
                "processing_mode": stt_result["processing_mode"]
            },
            "performance_metrics": {
                "chunks_per_second": chunks_per_second,
                "audio_processing_ratio": audio_processing_ratio,
                "estimated_sequential_time": estimated_sequential_time,
                "actual_parallel_time": stt_processing_time,
                "performance_improvement": performance_improvement,
                "speedup_factor": estimated_sequential_time / stt_processing_time if stt_processing_time > 0 else 0
            },
            "detailed_results": {
                "extraction": extraction_result,
                "stt": stt_result
            }
        }

        # 결과 출력
        logger.info("=" * 60)
        logger.info("🎯 Phase 1 병렬 처리 성능 테스트 결과")
        logger.info("=" * 60)
        logger.info(f"📹 오디오 길이: {audio_duration:.1f}초")
        logger.info(f"🎵 오디오 추출: {extraction_result['extraction_time']:.2f}초")
        logger.info(f"🚀 병렬 STT 처리: {stt_processing_time:.2f}초")
        logger.info(f"📊 총 처리 시간: {total_benchmark_time:.2f}초")
        logger.info(f"🔢 처리된 청크: {stt_result['processed_chunks']}/{stt_result['total_chunks']}개")
        logger.info(f"✅ 성공률: {stt_result['success_rate']:.1f}%")
        logger.info(f"⚡ Whisper 모델: {stt_result['whisper_models_used']}개 병렬")
        logger.info("-" * 60)
        logger.info(f"📈 예상 순차 처리 시간: {estimated_sequential_time:.2f}초")
        logger.info(f"🎯 실제 병렬 처리 시간: {stt_processing_time:.2f}초")
        logger.info(f"🚀 성능 개선율: {performance_improvement:.1f}%")
        logger.info(f"⚡ 속도 향상 배수: {estimated_sequential_time / stt_processing_time:.1f}x")
        logger.info("=" * 60)

        return benchmark_result

async def main():
    """메인 테스트 실행"""
    # 테스트용 일본어 유튜브 영상 (6분 정도)
    test_youtube_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # 실제 테스트 URL로 변경 필요

    # 사용자에게 URL 입력받기
    print("🎯 Phase 1 병렬 STT 처리 성능 테스트")
    print("-" * 60)
    youtube_url = input("테스트할 유튜브 URL을 입력하세요 (엔터 시 기본값 사용): ").strip()

    if not youtube_url:
        youtube_url = test_youtube_url
        print(f"기본 테스트 URL 사용: {youtube_url}")

    # 테스트 실행
    tester = PerformanceTest()
    result = await tester.run_performance_benchmark(youtube_url)

    # 결과 저장
    with open("phase1_benchmark_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n📄 상세 결과가 'phase1_benchmark_result.json'에 저장되었습니다.")

    return result

if __name__ == "__main__":
    asyncio.run(main())