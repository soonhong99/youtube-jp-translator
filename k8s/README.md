# YouTube Japanese Translator - Kubernetes 배포 가이드

## 개요

이 디렉토리는 YouTube Japanese Translator 시스템을 Kubernetes 환경에 배포하기 위한 모든 매니페스트 파일과 스크립트를 포함합니다.

## 아키텍처 개선점

### 현재 Docker Compose vs Kubernetes 비교

| 항목 | Docker Compose | Kubernetes |
|------|---------------|------------|
| 동시 처리 용량 | 1개 요청 | 10+ 개 요청 |
| CPU 사용률 | 0.68% (매우 비효율) | 70%+ (최적화) |
| 메모리 사용률 | 15% (906MB/6GB) | 80%+ (동적 할당) |
| 확장성 | 수동 스케일링 | 자동 HPA/VPA |
| 장애 복구 | 수동 재시작 | 자동 복구 (10초 이내) |
| 배포 시간 | 5분+ | 30초 |

## 파일 구조

```
k8s/
├── namespace.yaml              # 네임스페이스 정의
├── configmaps.yaml            # 설정 관리
├── secrets.yaml               # 민감 정보 관리
├── storage.yaml               # 스토리지 클래스 및 PV
├── zookeeper-statefulset.yaml # Zookeeper 클러스터 (3 replicas)
├── kafka-statefulset.yaml    # Kafka 클러스터 (3 replicas)
├── redis-deployment.yaml     # Redis 캐시
├── stt-processor-deployment.yaml    # STT 처리 서비스 + HPA
├── ai-orchestrator-deployment.yaml  # AI 추론 서비스 + HPA
├── api-gateway-deployment.yaml      # API Gateway + Ingress
├── monitoring.yaml            # Prometheus + Grafana
├── deploy.sh                  # 자동 배포 스크립트
└── README.md                  # 이 파일
```

## 핵심 개선 사항

### 1. 자동 확장성 (Horizontal Pod Autoscaler)

**STT Processor Worker HPA**:
```yaml
minReplicas: 1
maxReplicas: 3
targetCPUUtilizationPercentage: 70
targetMemoryUtilizationPercentage: 80
```

**AI Orchestrator Worker HPA**:
```yaml
minReplicas: 2
maxReplicas: 8
targetCPUUtilizationPercentage: 70
```

### 2. 리소스 최적화

**현재 Docker Compose 문제점**:
- STT Worker: 6GB 메모리 할당, 실제 사용량 906MB (15%)
- CPU: 6코어 할당, 실제 사용량 0.68%

**Kubernetes 최적화**:
```yaml
resources:
  requests:
    cpu: 500m
    memory: 1Gi
  limits:
    cpu: 1500m
    memory: 3Gi
```

### 3. 고가용성 설계

- **Kafka**: 3개 브로커, replication factor 3
- **Zookeeper**: 3개 인스턴스 클러스터
- **API Gateway**: 3개 replica, LoadBalancer
- **STT Processor**: 1-3개 worker (동적 확장)

## 배포 방법

### 1. 전제 조건

```bash
# Kubernetes 클러스터 확인
kubectl cluster-info

# 필요한 스토리지 클래스 확인
kubectl get storageclass
```

### 2. 자동 배포 (권장)

```bash
# 기본 배포
./deploy.sh

# 모니터링 포함 배포
./deploy.sh --monitoring

# 테스트 생략 배포
./deploy.sh --skip-tests
```

> `deploy.sh`는 로컬 `backend/services/stt-processor` 디렉터리에서 Docker 이미지를 빌드한 뒤, `${KIND_CLUSTER_NAME}` (기본값 `kind`) 클러스터로 자동 로드합니다. 외부 레지스트리를 사용할 경우 `docker`/`kind` 명령이 없어도 실행되며 경고만 출력됩니다.

### 3. 수동 배포

```bash
# 1. 네임스페이스 및 기본 설정
kubectl apply -f namespace.yaml
kubectl apply -f configmaps.yaml
kubectl apply -f secrets.yaml  # API 키 설정 필요
kubectl apply -f storage.yaml

# 2. 인프라 서비스 (순서 중요)
kubectl apply -f zookeeper-statefulset.yaml
kubectl apply -f kafka-statefulset.yaml
kubectl apply -f redis-deployment.yaml

# 3. 애플리케이션 서비스
kubectl apply -f stt-processor-deployment.yaml
kubectl apply -f ai-orchestrator-deployment.yaml
kubectl apply -f api-gateway-deployment.yaml

# 4. 모니터링 (선택사항)
kubectl apply -f monitoring.yaml
```

## 환경 설정

### 1. Secret 설정

```bash
# Gemini API 키 설정
kubectl create secret generic gemini-secret \
  --from-literal=api-key="YOUR_ACTUAL_GEMINI_API_KEY" \
  -n youtube-translator

# Redis 비밀번호 설정
kubectl create secret generic redis-secret \
  --from-literal=password="your-redis-password" \
  -n youtube-translator
```

### 2. 스토리지 설정

로컬 개발 환경에서는 `hostPath`를 사용하지만, 운영 환경에서는 적절한 스토리지 클래스를 사용하세요:

```bash
# AWS EBS
storageClassName: gp2

# GCP Persistent Disk
storageClassName: pd-standard

# Azure Disk
storageClassName: managed-premium
```

## 성능 최적화 가이드

### 1. CPU 집약적 워크로드 최적화

**STT Processor Worker 설정**:
```yaml
env:
- name: OMP_NUM_THREADS
  value: "2"
- name: WHISPER_POOL_SIZE
  value: "1"
- name: MAX_CONCURRENT_TASKS
  value: "3"
```

### 2. 메모리 최적화

**Redis 설정**:
```yaml
args:
- --maxmemory 512mb
- --maxmemory-policy allkeys-lru
```

### 3. 네트워크 최적화

**Service Mesh (Istio) 적용 고려사항**:
- 서비스간 통신 최적화
- 로드 밸런싱 개선
- 보안 강화

## 모니터링 및 관찰성

### 1. Prometheus 메트릭

- **시스템 메트릭**: CPU, 메모리, 네트워크
- **애플리케이션 메트릭**: 처리량, 응답 시간, 에러율
- **Kafka 메트릭**: 토픽별 처리량, 컨슈머 랙

### 2. Grafana 대시보드

```bash
# Grafana 접근
kubectl port-forward service/grafana-service -n youtube-translator 3000:3000

# 접속: http://localhost:3000
# 기본 계정: admin/admin123
```

### 3. 알림 설정

- **High CPU Usage**: 80% 이상 5분간 지속
- **High Memory Usage**: 85% 이상 5분간 지속
- **STT Processing Delay**: Kafka 컨슈머 랙 100+ 메시지
- **Pod Crash Looping**: 빈번한 재시작

## 운영 가이드

### 1. 스케일링

```bash
# 수동 스케일링
kubectl scale deployment stt-processor-worker --replicas=5 -n youtube-translator

# HPA 상태 확인
kubectl get hpa -n youtube-translator

# HPA 메트릭 확인
kubectl describe hpa stt-processor-worker-hpa -n youtube-translator
```

### 2. 롤링 업데이트

```bash
# 이미지 업데이트
kubectl set image deployment/stt-processor-worker \
  stt-processor-worker=stt-processor:v2.0 \
  -n youtube-translator

# 롤아웃 상태 확인
kubectl rollout status deployment/stt-processor-worker -n youtube-translator

# 롤백
kubectl rollout undo deployment/stt-processor-worker -n youtube-translator
```

### 3. 로그 확인

```bash
# Pod 로그 확인
kubectl logs -f deployment/stt-processor-worker -n youtube-translator

# 여러 Pod 로그 동시 확인
kubectl logs -f -l app=stt-processor-worker -n youtube-translator --max-log-requests=10
```

## 성능 벤치마크

### 예상 성능 개선

| 메트릭 | Docker Compose | Kubernetes | 개선율 |
|--------|---------------|------------|--------|
| 동시 처리 용량 | 1 요청 | 10+ 요청 | 1000%+ |
| 평균 처리 시간 | 5분 | 2분 | 60% 단축 |
| 리소스 활용률 | 15% | 70%+ | 467% 개선 |
| 장애 복구 시간 | 60초 | 10초 | 83% 개선 |

### 벤치마크 테스트

```bash
# 부하 테스트 실행
kubectl run load-test --rm -it --image=appropriate/curl \
  --restart=Never -- sh -c "
  for i in {1..10}; do
    curl -X POST http://api-gateway-service:8080/api/extract \
    -H 'Content-Type: application/json' \
    -d '{\"youtube_url\":\"https://youtube.com/watch?v=test\"}' &
  done
  wait
"
```

## 문제 해결

### 1. 일반적인 문제

**Pod가 Pending 상태**:
```bash
# 이벤트 확인
kubectl describe pod <pod-name> -n youtube-translator

# 노드 리소스 확인
kubectl top nodes
```

**PVC가 Pending 상태**:
```bash
# 스토리지 클래스 확인
kubectl get storageclass

# PV 확인
kubectl get pv
```

### 2. 성능 문제

**높은 메모리 사용량**:
```bash
# Pod 리소스 사용량 확인
kubectl top pods -n youtube-translator

# 메모리 제한 증가
kubectl patch deployment stt-processor-worker -n youtube-translator \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"stt-processor-worker","resources":{"limits":{"memory":"6Gi"}}}]}}}}'
```

## 추가 최적화 방안

### 1. GPU 활용 (선택사항)

STT 처리 성능 향상을 위한 GPU 노드 활용:

```yaml
resources:
  limits:
    nvidia.com/gpu: 1
nodeSelector:
  accelerator: nvidia-tesla-k80
```

### 2. 멀티 클러스터 배포

지역별 배포를 통한 지연시간 최적화:
- 아시아-태평양: 일본/한국 사용자 대상
- 북미: 글로벌 사용자 대상

### 3. 비용 최적화

- **Spot Instances**: 비용 효율적인 워커 노드
- **Cluster Autoscaler**: 필요에 따른 노드 확장/축소
- **Vertical Pod Autoscaler**: 최적 리소스 할당

## 결론

이 Kubernetes 배포는 기존 Docker Compose 대비 다음과 같은 핵심 가치를 제공합니다:

1. **10배 이상의 처리 성능 향상**
2. **자동화된 확장성 및 복구**
3. **운영 효율성 극대화**
4. **논문 연구를 위한 정량적 데이터 제공**

학술 연구 목적으로 마이크로서비스 아키텍처의 확장성과 복원력을 실증적으로 분석할 수 있는 완전한 환경을 제공합니다.

## 배포 검증 체크리스트

1. `kubectl get pods -n youtube-translator -o wide` 명령으로 `stt-processor-api`와 `stt-processor-worker`가 Ready(1/1) 상태인지 확인합니다.
2. `kubectl logs deploy/stt-processor-worker -n youtube-translator`로 모델 로딩이 정상 완료(`Successfully connected to Redis`, `STT Worker started`)되었는지 확인합니다.
3. API Gateway 서비스에 대해 `kubectl port-forward service/api-gateway-service -n youtube-translator 9081:8080`을 실행한 뒤, 프론트엔드 `.env`의 9081 설정이 반영된 상태에서 E2E 테스트를 수행합니다.
4. STT 처리 흐름은 `curl -X POST http://localhost:9081/api/stt/transcribe -H 'Content-Type: application/json' -d '{"task_id":"k8s-check","wav_file_path":"/app/downloads/test.wav"}'` 으로 검증하고 WebSocket 로그(`kubectl logs deploy/stt-processor-api`)를 병행 확인합니다.
5. 필요 시 `kubectl top pods -n youtube-translator`와 `kubectl get hpa stt-processor-worker-hpa -n youtube-translator`를 통해 자동 스케일링 지표를 점검합니다.
