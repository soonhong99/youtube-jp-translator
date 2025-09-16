#!/usr/bin/env python3
"""
Phase 3 시스템 종합 검증 스크립트
- 서비스 헬스 체크
- 스트리밍 번역 플로우 검증
- Phase 3 지능형 버퍼링 + API 최적화 검증
- 엔드투엔드 완전 자동 테스트
"""

import asyncio
import json
import time
import logging
import sys
import argparse
from typing import Dict, List, Optional, Any
import aiohttp
import websockets
from dataclasses import dataclass, asdict
import subprocess
import tempfile
import os

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class ValidationResult:
    test_name: str
    success: bool
    duration: float
    details: Dict[str, Any]
    error: Optional[str] = None

class Phase3Validator:
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.results: List[ValidationResult] = []
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def validate_service_health(self) -> ValidationResult:
        """서비스 헬스체크"""
        start_time = time.time()
        details = {}

        services = [
            ("API Gateway", f"{self.base_url}/health"),
            ("STT Processor", f"{self.base_url.replace('8080', '8001')}/health"),
            ("AI Orchestrator", f"{self.base_url.replace('8080', '8002')}/health"),
            ("Streaming STT", f"{self.base_url.replace('8080', '8007')}/health"),
            ("Performance Monitor", f"{self.base_url.replace('8080', '8006')}/health"),
            ("API Optimization", f"{self.base_url.replace('8080', '8009')}/health"),
            ("Intelligent Buffering", f"{self.base_url.replace('8080', '8008')}/health"),
        ]

        healthy_count = 0
        for name, url in services:
            try:
                async with self.session.get(url, timeout=5) as response:
                    if response.status == 200:
                        healthy_count += 1
                        details[name] = "healthy"
                    else:
                        details[name] = f"unhealthy (HTTP {response.status})"
            except Exception as e:
                details[name] = f"error: {str(e)}"

        success = healthy_count >= 5  # 최소 5개 서비스는 정상이어야 함
        duration = time.time() - start_time

        return ValidationResult(
            test_name="service_health",
            success=success,
            duration=duration,
            details=details,
            error=None if success else f"Only {healthy_count}/{len(services)} services healthy"
        )

    async def validate_streaming_rollout(self) -> ValidationResult:
        """스트리밍 롤아웃 설정"""
        start_time = time.time()

        try:
            # 롤아웃을 100%로 설정
            async with self.session.post(
                f"{self.base_url}/api/streaming/rollout",
                json={"percentage": 100},
                timeout=10
            ) as response:
                if response.status != 200:
                    raise Exception(f"Rollout setting failed: HTTP {response.status}")

                rollout_data = await response.json()

            # 설정 확인
            async with self.session.get(
                f"{self.base_url}/api/streaming/rollout",
                timeout=10
            ) as response:
                if response.status != 200:
                    raise Exception(f"Rollout check failed: HTTP {response.status}")

                status_data = await response.json()

            duration = time.time() - start_time
            success = status_data.get("streaming_percentage") == 100

            return ValidationResult(
                test_name="streaming_rollout",
                success=success,
                duration=duration,
                details={
                    "rollout_setting": rollout_data,
                    "rollout_status": status_data
                }
            )

        except Exception as e:
            duration = time.time() - start_time
            return ValidationResult(
                test_name="streaming_rollout",
                success=False,
                duration=duration,
                details={},
                error=str(e)
            )

    async def generate_test_audio(self) -> str:
        """테스트용 음성 파일 생성 (1초 사인파)"""
        try:
            # 임시 WAV 파일 생성
            fd, temp_path = tempfile.mkstemp(suffix='.wav')
            os.close(fd)

            # FFmpeg로 1초 사인파 생성 (440Hz)
            subprocess.run([
                'ffmpeg', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                '-ar', '16000', '-ac', '1', '-y', temp_path
            ], check=True, capture_output=True)

            logger.info(f"✅ 테스트 음성 파일 생성: {temp_path}")
            return temp_path

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ 음성 파일 생성 실패: {e}")
            raise Exception("FFmpeg를 사용해 테스트 음성 파일을 생성할 수 없습니다")
        except FileNotFoundError:
            logger.error("❌ FFmpeg가 설치되지 않았습니다")
            raise Exception("FFmpeg가 필요합니다. brew install ffmpeg로 설치하세요")

    async def validate_streaming_translation(self) -> ValidationResult:
        """스트리밍 번역 완전 검증"""
        start_time = time.time()
        task_id = f"e2e_test_{int(time.time())}"

        try:
            # 1. 테스트 음성 파일 생성
            audio_path = await self.generate_test_audio()

            # 2. 스트리밍 요청 전송 (컨테이너 내부 경로로)
            container_audio_path = f"/tmp/{os.path.basename(audio_path)}"

            # Docker 컨테이너에 파일 복사
            subprocess.run([
                'docker', 'cp', audio_path,
                f'streaming-stt-processor:{container_audio_path}'
            ], check=True, capture_output=True)

            request_payload = {
                "task_id": task_id,
                "audio_file_path": container_audio_path,
                "mode": "streaming",
                "chunk_duration": 0.5,
                "overlap_duration": 0.1
            }

            # 3. 스트리밍 번역 요청
            async with self.session.post(
                f"{self.base_url}/api/streaming/translate",
                json=request_payload,
                timeout=30
            ) as response:
                if response.status != 200:
                    raise Exception(f"Streaming request failed: HTTP {response.status}")

                stream_response = await response.json()
                logger.info(f"🚀 스트리밍 요청 전송: {stream_response}")

            # 4. WebSocket으로 결과 수신 (30초 타임아웃)
            ws_url = f"ws://localhost:8080/api/streaming/ws/{task_id}"
            received_messages = []

            try:
                async with websockets.connect(ws_url) as websocket:
                    # 작업 바인딩
                    await websocket.send(json.dumps({
                        "type": "bind_task",
                        "task_id": task_id
                    }))

                    # 결과 수신 (최대 30초)
                    end_time = time.time() + 30
                    while time.time() < end_time:
                        try:
                            message = await asyncio.wait_for(
                                websocket.recv(),
                                timeout=5.0
                            )
                            data = json.loads(message)
                            received_messages.append(data)

                            logger.info(f"📨 WS 메시지 수신: {data.get('type', 'unknown')}")

                            # Phase 3 결과 확인
                            if data.get("type") == "optimized_translation_result":
                                logger.info("🎯 Phase 3 최적화 번역 결과 수신!")
                                break

                        except asyncio.TimeoutError:
                            continue
                        except websockets.exceptions.ConnectionClosed:
                            break

            except Exception as ws_error:
                logger.warning(f"⚠️ WebSocket 연결 실패: {ws_error}")

            # 5. 결과 분석
            stt_chunks = [m for m in received_messages if m.get("type") == "stt_chunk"]
            translation_results = [m for m in received_messages if m.get("type") == "translation_result"]
            optimized_results = [m for m in received_messages if m.get("type") == "optimized_translation_result"]

            duration = time.time() - start_time
            success = len(stt_chunks) > 0 and len(received_messages) > 0

            details = {
                "request_payload": request_payload,
                "stream_response": stream_response,
                "total_messages": len(received_messages),
                "stt_chunks": len(stt_chunks),
                "translation_results": len(translation_results),
                "optimized_results": len(optimized_results),
                "phase3_working": len(optimized_results) > 0,
                "messages": received_messages[:10]  # 처음 10개 메시지만
            }

            # 임시 파일 정리
            try:
                os.unlink(audio_path)
            except:
                pass

            return ValidationResult(
                test_name="streaming_translation",
                success=success,
                duration=duration,
                details=details,
                error=None if success else "No STT chunks or messages received"
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"❌ 스트리밍 번역 검증 실패: {e}")
            return ValidationResult(
                test_name="streaming_translation",
                success=False,
                duration=duration,
                details={},
                error=str(e)
            )

    async def validate_phase3_metrics(self) -> ValidationResult:
        """Phase 3 메트릭 및 상태 검증"""
        start_time = time.time()

        try:
            details = {}

            # API Optimization 메트릭
            async with self.session.get(
                f"{self.base_url.replace('8080', '8009')}/metrics",
                timeout=10
            ) as response:
                if response.status == 200:
                    details["api_optimization_metrics"] = await response.json()
                else:
                    details["api_optimization_metrics"] = f"HTTP {response.status}"

            # Intelligent Buffering 메트릭
            async with self.session.get(
                f"{self.base_url.replace('8080', '8008')}/metrics",
                timeout=10
            ) as response:
                if response.status == 200:
                    details["intelligent_buffering_metrics"] = await response.json()
                else:
                    details["intelligent_buffering_metrics"] = f"HTTP {response.status}"

            # Phase 3 통합 메트릭
            async with self.session.get(
                f"{self.base_url}/api/phase3/metrics",
                timeout=10
            ) as response:
                if response.status == 200:
                    details["phase3_integration_metrics"] = await response.json()
                else:
                    details["phase3_integration_metrics"] = f"HTTP {response.status}"

            duration = time.time() - start_time
            success = len([k for k, v in details.items() if isinstance(v, dict)]) >= 2

            return ValidationResult(
                test_name="phase3_metrics",
                success=success,
                duration=duration,
                details=details
            )

        except Exception as e:
            duration = time.time() - start_time
            return ValidationResult(
                test_name="phase3_metrics",
                success=False,
                duration=duration,
                details={},
                error=str(e)
            )

    async def run_full_validation(self) -> Dict[str, Any]:
        """전체 검증 실행"""
        logger.info("🚀 Phase 3 시스템 종합 검증 시작")

        validation_tests = [
            self.validate_service_health(),
            self.validate_streaming_rollout(),
            self.validate_streaming_translation(),
            self.validate_phase3_metrics()
        ]

        results = await asyncio.gather(*validation_tests, return_exceptions=True)

        # 결과 처리
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"❌ 검증 중 예외 발생: {result}")
                self.results.append(ValidationResult(
                    test_name="exception",
                    success=False,
                    duration=0.0,
                    details={},
                    error=str(result)
                ))
            else:
                self.results.append(result)

        # 결과 요약
        total_tests = len(self.results)
        passed_tests = len([r for r in self.results if r.success])
        total_duration = sum(r.duration for r in self.results)

        summary = {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": total_tests - passed_tests,
            "success_rate": passed_tests / total_tests if total_tests > 0 else 0.0,
            "total_duration": total_duration,
            "results": [asdict(r) for r in self.results]
        }

        # 로그 출력
        logger.info(f"📊 검증 완료: {passed_tests}/{total_tests} 통과 ({summary['success_rate']:.1%})")
        for result in self.results:
            status = "✅" if result.success else "❌"
            logger.info(f"{status} {result.test_name}: {result.duration:.2f}s")
            if result.error:
                logger.error(f"   오류: {result.error}")

        return summary

def main():
    parser = argparse.ArgumentParser(description="Phase 3 시스템 종합 검증")
    parser.add_argument("--base-url", default="http://localhost:8080", help="API Gateway URL")
    parser.add_argument("--output", help="결과를 JSON 파일로 저장")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 로그 출력")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    async def run_validation():
        async with Phase3Validator(args.base_url) as validator:
            summary = await validator.run_full_validation()

            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    json.dump(summary, f, indent=2, ensure_ascii=False)
                logger.info(f"💾 결과를 {args.output}에 저장했습니다")

            # 종료 코드 설정
            if summary["success_rate"] >= 0.8:  # 80% 이상 성공
                logger.info("🎉 Phase 3 시스템 검증 성공!")
                return 0
            else:
                logger.error("💥 Phase 3 시스템 검증 실패!")
                return 1

    exit_code = asyncio.run(run_validation())
    sys.exit(exit_code)

if __name__ == "__main__":
    main()