Phase 3 – Implementation Wrap‑Up (Build, Fixes, and Verification)

Scope
- API Gateway Phase 3 연동 보강 (지능형 버퍼링 트리거 및 최적화 번역 결과 WS 전파)
- 짧은 WAV 청킹 이슈 해결 (최소 1개 청크 보장, VAD 완화)
- Performance Monitor 빌드 실패(psutil) 수정
- Redis DNS(api-gateway) 이슈 해결
- /api/streaming/status 중복 라우트 정리
- Streaming Coordinator 초기화 백오프/헬스 개선
- 검증용 스크립트 추가 (WS 테스트, WAV 생성)

Changed Files
- backend/services/api-gateway/src/main.py
  - Phase3Integration을 StreamingHandler에 주입하도록 초기화 순서 수정
  - /api/streaming/status 중복 라우트 제거
- backend/services/api-gateway/src/streaming_handler.py
  - Kafka 컨슈머 토픽 추가: optimized_translation_results
  - STT 청크 수신 시 Phase 3 버퍼링 호출 및 intelligent_translation_requests 발행
  - optimized_translation_results WS 전파 핸들러 추가
- backend/services/streaming-stt-processor/src/audio_chunker.py
  - 짧은 오디오도 최소 1개 청크 생성, VAD 완화, 파일명 생성 시 time 기반으로 수정
- backend/services/streaming-stt-processor/src/streaming_worker.py
  - STT 결과 None 가드(전송 시도 방지)
- backend/services/performance-monitor/Dockerfile
  - build-essential/gcc/python3-dev 설치로 psutil 빌드 성공
- backend/docker-compose.yml
  - api-gateway 서비스에 links: redis 추가로 컨테이너 내 DNS 보강
- backend/services/streaming-coordinator/src/main.py
  - 초기화 비차단(create_task) + 백오프 재시도 + ready 플래그/헬스 응답 개선
- backend/services/api-optimization/requirements.txt
  - stdlib 항목(hashlib/difflib) 제거, rapidfuzz 핀 수정
- backend/scripts/test_streaming_ws.py, backend/scripts/gen_wav.py 추가

Build & Run (요약)
- 이미지 빌드: api-gateway, streaming-stt-processor, performance-monitor OK
- 컨테이너 기동: Zookeeper/Kafka/Redis, streaming-stt-processor, api-gateway, performance-monitor OK
- Phase 3 서비스(api-optimization) 수정 후 빌드/기동 OK (intelligent-buffering은 미기동)

Health/Metrics
- API Gateway: /health OK, /metrics OK
- Streaming STT Processor: /health OK, /stats/metrics OK
- Performance Monitor: /health OK, /metrics OK
- Streaming Coordinator: 초기화 백오프 후 ready → /health status 필드로 상태 제공(HTTP 200 유지)

Functional Verification (핵심)
- 롤아웃 제어: /api/streaming/rollout 100% 설정 성공(이전 Redis DNS 이슈 해소)
- 스트리밍 요청: 1초 WAV로 /api/streaming/translate 호출 시 mode=streaming 처리로 전환
- 청킹: “2개 청크 생성” 로그로 짧은 WAV 청킹 성공(이전 0 청크 문제 해결)
- STT None 가드: 텍스트가 없는 청크에서의 전송 에러 방지(새 태스크에서 재발 없음)
- Phase 3: Gateway에서 STT 청크 수신→버퍼링 호출→지능형 번역 요청 발행 로직 구현 완료

Quick Commands
- 빌드
  - cd backend
  - docker-compose -f docker-compose.yml -f docker-compose.streaming.yml build api-gateway streaming-stt-processor performance-monitor
  - docker-compose -f docker-compose.yml -f docker-compose.phase3.yml build api-optimization
- 기동
  - docker-compose -f docker-compose.yml up -d
  - docker-compose -f docker-compose.yml -f docker-compose.streaming.yml up -d streaming-stt-processor performance-monitor
  - docker-compose -f docker-compose.yml -f docker-compose.phase3.yml up -d api-optimization
- 상태/메트릭
  - curl http://localhost:8080/health; curl http://localhost:8080/metrics | head
  - curl http://localhost:8007/health; curl http://localhost:8007/metrics | head
  - curl http://localhost:8006/health; curl http://localhost:8006/metrics | head
- 스트리밍/E2E
  - 롤아웃 100%: curl -X POST http://localhost:8080/api/streaming/rollout -H 'Content-Type: application/json' -d '{"percentage":100}'
  - WAV 생성: python backend/scripts/gen_wav.py --out ./backend/services/streaming-stt-processor/tmp/test.wav --seconds 1
  - (또는 STT 컨테이너 내부 /tmp/test.wav 생성)
  - 요청: curl -X POST http://localhost:8080/api/streaming/translate -H 'Content-Type: application/json' -d '{"task_id":"s6","audio_file_path":"/tmp/test.wav","mode":"streaming","chunk_duration":0.5,"overlap_duration":0.1}'
  - WS 테스트(로컬): python backend/scripts/test_streaming_ws.py --task s6 --timeout 20

Notes & Known Gaps
- STT 실텍스트: 테스트 톤(사인파)은 텍스트가 없어 STT 결과가 비어 있을 수 있습니다. 실제 음성(5–10초) WAV로 재검증하면 stt_chunk/translation_result WS 수신이 용이합니다.
- Intelligent Buffering 서비스: 현재 미기동이므로 Phase 3 버퍼 트리거는 API 레벨에서만 검증했습니다. 필요 시 backend/docker-compose.phase3.yml의 intelligent-buffering를 빌드/기동해 완전한 Phase 3 경로를 사용할 수 있습니다(해당 서비스 requirements가 큼).
- API Optimization Kafka 경로: intelligent_translation_requests → optimized_translation_results 비동기 배치 경로의 결과 발행(send_translation_result)은 캐시 히트 또는 배치 처리 콜백에서 수행되어야 합니다. 현재 배치 처리 결과의 Kafka 전송이 실행 경로에서 확실히 호출되는지 점검이 필요합니다(필요 시 DynamicBatcher가 처리 완료 후 결과를 send_translation_result로 보내도록 후크 추가 권장).
- /api/streaming/status: 중복 라우트 제거 완료. 상태는 streaming_handler의 Redis 조회/폴백 로직을 사용합니다.

Next Steps (Optional)
- Intelligent Buffering 서비스 기동 및 /buffer/add 트리거 검증
- DynamicBatcher 처리 완료 후 optimized_translation_results 발행 후크 보강(완전 자동 E2E)
- Grafana Phase 3 대시보드 패널 구성 및 프로비저닝 적용

결론
- 요청하신 1,2,4번(Phase 3 연동, 짧은 WAV 청킹 보정, PerfMon 빌드)과 추가로 Redis DNS 문제 및 상태 API/Coordinator 안정화까지 마쳤습니다. 핵심 경로(HTTP→Kafka→Streaming STT)와 제어/메트릭은 정상 동작합니다. 실제 음성 WAV로 실행하시면 WS에서 stt_chunk 수신까지 자연스럽게 확인하실 수 있습니다. optimized_translation_results WS 전파 경로도 구현되어 있으며, Phase 3 전체 자동 플로우는 intelligent-buffering 기동 및 api-optimization 배치 결과 발행 후크 확정 시 완전 자동화됩니다.

