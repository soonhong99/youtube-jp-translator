# Kubernetes 전환 문제 해결 보고서

## 1. 변경 사항 요약

### 1.1 프론트엔드/환경 변수 수정
- `frontend/.env`: API GW와 WebSocket 엔드포인트를 모두 `http://localhost:9081` / `ws://localhost:9081/api`로 통일하여 K8s 포트 포워딩과 일치시켰습니다. 프론트 요청 주소 불일치로 발생하던 네트워크 오류를 제거했습니다.

### 1.2 STT Docker 이미지 경량화
- `backend/services/stt-processor/Dockerfile`: 빌드 시점 Whisper 모델 다운로드를 제거하여 이미지 크기(약 1.7GB→수백 MB 수준)를 축소했습니다. 모델은 PVC에 런타임 캐시되도록 설계했습니다. Kind 노드 디스크 부족 문제를 방지하기 위함입니다.

### 1.3 Kubernetes 매니페스트 개선
- `k8s/stt-processor-deployment.yaml`:
  - `imagePullPolicy: IfNotPresent`, 초기 `replicas` 1개, `resources` 축소(요청 500m/1Gi) 및 `HPA(1~3)` 조정.
  - `podAffinity` 유지 + `nodeSelector`로 STT API/워커를 동일 워커 노드에 스케줄링해 PVC(RWO) 요구사항 충족.
  - `envFrom`에 `redis-config` 포함, `PVC` 재정의(`ReadWriteOnce`, 20Gi/5Gi), `stt-chunks-tmp`는 `emptyDir`.
  - 이전 `hostnetwork` 프록시 의존성을 제거하고 순수 K8s Service 구조로 전환.
- `k8s/storage.yaml`, `k8s/simple-pvcs.yaml`: `shared-storage` StorageClass(hostPath, `DirectoryOrCreate`) 생성, STT용 PV/PVC를 RWO로 재정의.
- `k8s/api-gateway-deployment.yaml`, `k8s/ai-orchestrator-deployment.yaml` 등: `imagePullPolicy: IfNotPresent` 적용.
- `k8s/configmaps.yaml`: STT 워커 스레드/풀 사이즈 및 타임아웃 값을 개발 환경에 맞게 축소.
- `k8s/deploy.sh`: `build_and_load_stt_image` 추가(docker build → kind load 자동화), 도구 미설치 시 경고 안내.
- `k8s/README.md`: 최신 리소스/HPA 값 반영 및 “배포 검증 체크리스트” 추가.

### 1.4 클러스터 정리 작업
- 기존 `stt-proxy` Deployment/Service 제거.
- 이전 PV/PVC/이미지를 삭제하고 새 `shared-storage` 기반 PV로 재구성.
- Docker 이미지/볼륨 정리(`docker image rm`, `docker system prune`)로 호스트와 Kind 노드의 디스크 여유 공간 확보.
- Kafka 토픽 14종(`stt_requests`, `stt_results` 등) 재생성.
- `test.wav` 대신 실제 음성 샘플 `sample.wav`(tts-synthesizer 샘플)를 STT PVC에 복사.

## 2. 변경 사유
1. **포트 불일치 제거**: 프론트 `.env` 및 포트 포워딩을 9081로 통일하여 `ERR_CONNECTION_RESET` 문제 해결.
2. **이미지 용량 및 저장소 압박 해소**: Whisper 모델을 이미지에 내장하지 않고 런타임 캐시로 전환해 Kind 노드 디스크 부족으로 인한 Zookeeper/Kafka CrashLoop를 방지.
3. **PVC 재설계**: 기존 RWX hostPath PV가 다중 노드에 적합하지 않아 바운딩 실패 → RWO 기반 `shared-storage`로 재구성.
4. **프록시 제거**: Docker Compose 상주 STT 대신 K8s 배포만 사용하도록 구성 정리.
5. **자동화 개선**: `deploy.sh`가 이미지 빌드/로딩까지 수행하도록 하여 `ErrImagePull` 방지.
6. **리소스 최적화**: 개발 환경에서 과한 리소스/HPA 설정을 낮춰 Pod 스케줄링 실패 감소.
7. **Kafka 토픽 보강**: STT 파이프라인이 의존하는 토픽들을 재생성하여 `Topic not found` 오류 제거.

## 3. 검증 결과
1. `kubectl get pods -n youtube-translator -o wide` 결과, `stt-processor-api`, `stt-processor-worker`, `kafka`, `zookeeper` 등 핵심 파드 모두 Ready 상태.
2. `kubectl logs stt-processor-worker-5c6ddd5d69-xmczx --since=60s`:
   - `/app/downloads/sample.wav` 처리 로그 → STT 완료 → AI Orchestrator 연동까지 정상 작동.
3. `kubectl exec kafka-57ff7859b4-8snw9 -- kafka-topics --list`:
   - `stt_requests`, `stt_results`, `ai_processing_requests` 등 14개 토픽 존재 확인.
4. `kubectl port-forward service/api-gateway-service 9081:8080` 후 `curl` 테스트:
   - `/health` → `{"status":"healthy"}`
   - `/api/stt/transcribe` 요청 → `{"status":"Queued","websocket_url":"/ws/k8s-check"}` 응답 획득.
5. `kubectl wait`/`logs`로 Zookeeper, Kafka, STT 파드가 재기동 후 안정화되었음을 확인.

## 4. 남은 이슈 / 주의 사항
1. **Gemini API Key 미설정**: `stt-processor` 및 `ai-orchestrator` 가 Gemini 초기화 실패 경고를 출력 중. 실제 번역 기능 사용 시 유효 키 등록 필요.
2. **Metrics Server 미설치**: `kubectl top`/HPA 지표가 `<unknown>`으로 표시. 리소스 모니터링이 필요하면 Metrics Server 또는 Prometheus 연동 필요.
3. **shared-storage PV 구조**: 현재 `whisper-models-pvc`가 `redis-storage-pv`에 바인딩. redis 추가 PV가 필요하다면 `storage.yaml` 조정 필요.
4. **디스크 여유 공간**: 현재 26Gi 정도 확보. 추가 이미지 빌드 시 주기적인 `docker system df` 확인 권장.

## 5. 다음 단계 제안
1. `./k8s/deploy.sh --skip-tests` 재실행으로 새 구조가 끝까지 자동 배포되는지 확인 (이미지 로드 포함).
2. 프론트엔드 빌드/실행 후 실제 UI에서 `/ws/{task_id}` WebSocket까지 동작 확인.
3. Metrics Server 또는 Prometheus 기반 감시를 보강하고, HPA 지표가 활성화되는지 확인.
4. Gemini API Key 설정 후 AI 단계까지 E2E 테스트.
5. 필요 시 `shared-storage` PV를 NFS/rook-ceph 등 RWX 스토리지로 전환하여 향후 멀티 워커 확장 대비.
