# Kubernetes 배포 및 문제 해결 과정 정리

## 📋 진행 상황 요약

### 초기 목표
- YouTube Japanese Translator 시스템을 Docker Compose에서 Kubernetes로 완전 이관
- 프론트엔드에서 바로 테스트 가능한 완성도 있는 배포 구현

### 현재 상태
- ✅ **WebSocket 연결 문제 해결 완료**
- ❌ **프론트엔드 네트워크 연결 에러 발생**

---

## 🔄 진행 과정 상세

### 1. 초기 Kubernetes 배포
- Kind 클러스터 구성 (4노드: control-plane + 3 workers)
- Zookeeper, Kafka, Redis 인프라 서비스 배포
- API Gateway, AI Orchestrator, YouTube Extractor 애플리케이션 서비스 배포

### 2. STT Processor 연결 문제 발생
**문제**: STT Processor 이미지가 Kind 클러스터에서 로드되지 않음
**원인**: Docker 이미지 태그 및 빌드 문제
**해결 시도**:
- 이미지 재빌드 및 Kind 클러스터 로드
- imagePullPolicy 수정
- 다양한 디버깅 시도

**최종 해결책**: STT Processor를 기존 Docker Compose에서 실행하고 Kubernetes에서 프록시로 연결
```yaml
# hostnetwork-stt-proxy.yaml
upstream stt_backend {
    server host.docker.internal:8001;
}
```

### 3. Docker Compose 포트 바인딩 수정
**문제**: STT 서비스가 127.0.0.1:8001에만 바인딩되어 Kind 클러스터에서 접근 불가
**해결**:
```yaml
# docker-compose.yml
ports:
  - "0.0.0.0:8001:8001"  # 127.0.0.1에서 0.0.0.0으로 변경
```

### 4. API Gateway WebSocket 프록시 수정
**문제**: WebSocket URL이 하드코딩되어 서비스 디스커버리 실패
**해결**:
```python
# 기존
stt_ws_url = f"ws://stt-processor-api:8001/ws/{task_id}"

# 수정
stt_service_url = SERVICES["stt_processor"].replace("http://", "ws://")
stt_ws_url = f"{stt_service_url}/ws/{task_id}"
```

### 5. Nginx 프록시에 WebSocket 지원 추가
**문제**: HTTP 프록시가 WebSocket 연결을 지원하지 않음
**해결**:
```nginx
# WebSocket support
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_read_timeout 86400;
```

---

## 🎯 현재 상태 분석

### ✅ 해결된 문제들
1. **STT 서비스 연결**: HTTP API 호출 정상 작동
2. **WebSocket 실시간 통신**: 완전히 해결됨
   ```
   ✅ 연결 성공: WebSocket established
   ✅ 실시간 메시지: {"status":"PROCESSING","progress":10,"step_detail":"..."}
   ```

### ❌ 현재 발생 중인 문제

#### 문제 1: 프론트엔드 네트워크 에러
```
POST http://localhost:9080/api/youtube/extract net::ERR_CONNECTION_RESET
AxiosError: Network Error
```

**원인 분석**:
1. **포트 충돌**: 프론트엔드가 9080 포트를 사용하지만, 현재 API Gateway는 9081 포트에서 작동
2. **포트 포워딩 문제**: 기존 9080 포트 포워딩이 비정상 상태
3. **환경 변수 불일치**: 프론트엔드 `.env` 파일이 업데이트되지 않음

#### 문제 2: 서비스 포트 매핑 혼재
- Kind 클러스터: API Gateway 서비스는 8080 포트
- 포트 포워딩 1: localhost:9080 → 문제 발생
- 포트 포워딩 2: localhost:9081 → 정상 작동
- 프론트엔드: localhost:9080 기대

---

## 🛠️ 현재 아키텍처

### Kubernetes 클러스터 내부
```
API Gateway (port 8080) ─┐
YouTube Extractor        │ ← Kubernetes Services
AI Orchestrator          │
Kafka, Redis, Zookeeper ─┘
```

### 하이브리드 연결
```
API Gateway (K8s) ─── Nginx Proxy (K8s) ─── STT Processor (Docker Compose)
                       ↳ WebSocket Support      ↳ host.docker.internal:8001
```

### 네트워크 플로우
```
Frontend (localhost:3000)
    ↓ API calls to localhost:9080 (문제!)
Kind Port Forward (localhost:9081) ← 실제 작동
    ↓
API Gateway Service (K8s)
    ↓
Various Services...
```

---

## 🚨 즉시 해결해야 할 문제

### 1. 포트 포워딩 정리
**현재 상황**:
- 9080 포트: 비정상 상태 (connection reset)
- 9081 포트: 정상 작동

**필요한 조치**:
1. 기존 9080 포트 포워딩 프로세스 종료
2. 9080 포트로 새로운 포트 포워딩 생성
3. 또는 프론트엔드 환경 변수를 9081로 변경

### 2. 프론트엔드 설정 업데이트
**파일**: `frontend/.env`
```
# 현재 (문제)
REACT_APP_API_GATEWAY_URL=http://localhost:9080

# 수정 필요
REACT_APP_API_GATEWAY_URL=http://localhost:9081
REACT_APP_WS_BASE_URL=ws://localhost:9081/api
```

### 3. STT 처리 에러
WebSocket은 연결되지만 STT 처리 자체가 실패:
```json
{"status":"FAILED","error":"STT processing failed or returned empty result"}
```
이는 별도 디버깅이 필요한 사항.

---

## 📊 성공한 테스트 결과

### HTTP API 테스트 (✅ 성공)
```bash
# YouTube 오디오 추출
curl -X POST http://localhost:9081/api/youtube/extract
# → {"file_path":"/app/downloads/...","duration":213.0}

# STT 요청
curl -X POST http://localhost:9081/api/stt/transcribe
# → {"task_id":"...","status":"Queued","websocket_url":"/ws/..."}
```

### WebSocket 테스트 (✅ 성공)
```python
# 실시간 메시지 수신 확인
{"task_id":"test-ws-complete","status":"PROCESSING","progress":0}
{"task_id":"test-ws-complete","status":"PROCESSING","progress":10}
```

---

## 🎯 다음 단계

### 즉시 해결 (Critical)
1. **포트 포워딩 복구**: 9080 포트 정상화 또는 프론트엔드 설정 변경
2. **E2E 테스트**: 프론트엔드 → 백엔드 전체 플로우 검증

### 중장기 개선 (Optional)
1. **STT Processor 완전 K8s 이관**: Docker Compose 의존성 제거
2. **모니터링 강화**: Prometheus/Grafana 추가
3. **로드밸런싱**: API Gateway 다중 인스턴스 최적화

---

## 📝 학습된 교훈

1. **하이브리드 아키텍처의 복잡성**: K8s + Docker Compose 혼재 시 네트워킹 복잡도 증가
2. **포트 포워딩 관리**: 개발 환경에서 포트 충돌 및 상태 관리 중요성
3. **WebSocket 프록시**: Nginx에서 WebSocket 지원을 위한 추가 설정 필요
4. **서비스 디스커버리**: 하드코딩 대신 환경 변수 활용의 중요성

---

## 💡 현재 상태 요약

**✅ 작동하는 것들**:
- Kubernetes 인프라 서비스들
- API Gateway HTTP 라우팅
- WebSocket 실시간 통신
- STT Proxy를 통한 Docker Compose 연결

**❌ 문제가 되는 것들**:
- 프론트엔드 → API Gateway 연결 (포트 문제)
- STT 처리 로직 (별도 이슈)

**🎯 다음 목표**:
포트 포워딩 정리 후 완전한 E2E 테스트 성공