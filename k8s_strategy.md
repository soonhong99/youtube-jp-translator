# STT 프로세서 병목지점 분석 및 Kubernetes 전환 전략

## 📊 현재 아키텍처 병목지점 심층 분석

### 1. STT 프로세서 리소스 현황 분석

#### 🔍 Docker Compose 설정 분석 (backend/docker-compose.yml:226-276)
```yaml
stt-processor-worker:
  deploy:
    resources:
      limits:
        cpus: '6'         # 기존 2 → 6 (300% 증가)
        memory: 6G        # 기존 4G → 6G (50% 증가)
      reservations:
        cpus: '2'         # 기존 1 → 2 (100% 증가)
        memory: 3G        # 기존 2G → 3G (50% 증가)
  environment:
    - MAX_WORKERS=4              # ThreadPoolExecutor 워커 수
    - WHISPER_POOL_SIZE=3        # Whisper 모델 풀 크기
    - MAX_CONCURRENT_TASKS=8     # 동시 처리 작업 수
    - CHUNK_BATCH_SIZE=6         # 청크 배치 크기
    - OMP_NUM_THREADS=4          # OpenMP 스레드 수
    - MKL_NUM_THREADS=4          # Intel MKL 스레드 수
```

#### 📈 실제 리소스 사용률 측정
```
Container: stt-processor-worker
CPU: 0.40% (유휴 상태)
Memory: 905.9MiB / 6GiB (14.74% 사용률)
```

### 2. Whisper 모델 풀링 vs Kubernetes Pod 풀링 비교 분석

#### 🧠 현재 Whisper 모델 풀링 전략 (streaming-stt-processor/src/whisper_pool.py)

**장점:**
- **메모리 효율성**: 3개 모델 인스턴스를 풀링하여 메모리 재사용
- **모델 로딩 최적화**: 초기화 시점에 모든 모델 로드 (cold start 방지)
- **CPU 스레드 최적화**:
  ```python
  # 8코어 시스템에서 3모델 → 4스레드/모델 (오버커밋 허용)
  if cpu_count >= 8:
      threads_per_model = max(3, min(6, (cpu_count * 3) // (self.pool_size * 2)))
  ```
- **컨텍스트 매니저**: 자동 리소스 관리 및 예외 처리

**단점:**
- **수직 스케일링 한계**: 단일 노드 CPU 코어 수에 제한
- **장애 회복성 부족**: 컨테이너 장애 시 전체 모델 풀 손실
- **리소스 고정 할당**: 유휴 시에도 6GB 메모리 점유

#### 🚀 Kubernetes Pod 풀링 전략 설계

**1. HorizontalPodAutoscaler (HPA) 기반 스케일링**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: stt-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: stt-processor-worker
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: External
    external:
      metric:
        name: kafka_consumer_lag
      target:
        type: AverageValue
        averageValue: "5"
```

**2. VerticalPodAutoscaler (VPA) 리소스 최적화**
```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: stt-worker-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: stt-processor-worker
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
    - containerName: stt-worker
      maxAllowed:
        cpu: 8
        memory: 12Gi
      minAllowed:
        cpu: 500m
        memory: 2Gi
```

### 3. 성능 병목지점 및 최적화 기회

#### 🎯 핵심 병목지점 식별

**A. Whisper 모델 로딩 병목**
```python
# 현재: 동기적 모델 로딩 (worker.py:434)
model = WhisperModel(model_size, device="cpu", compute_type="int8")

# 문제점:
# - 초기화 시 3개 모델 순차 로딩 (약 30-60초)
# - Cold start 시 모든 모델 재로딩 필요
```

**K8s 해결책: Model-as-a-Service 패턴**
```yaml
# 모델 서빙 전용 Pod
apiVersion: apps/v1
kind: Deployment
metadata:
  name: whisper-model-server
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: whisper-server
        image: whisper-model-server:latest
        resources:
          requests:
            cpu: 1
            memory: 2Gi
          limits:
            cpu: 2
            memory: 4Gi
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 60  # 모델 로딩 대기
```

**B. 동시성 처리 병목**
```python
# 현재: ThreadPoolExecutor 제한 (worker.py:64-66)
self.max_workers = max_workers  # 4개 고정
self.executor = ThreadPoolExecutor(max_workers=max_workers)

# 문제점:
# - 고정된 워커 수로 피크 시간 대응 부족
# - CPU 코어 대비 비효율적 활용
```

**K8s 해결책: KEDA 기반 Event-Driven 스케일링**
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: stt-worker-scaler
spec:
  scaleTargetRef:
    name: stt-processor-worker
  minReplicaCount: 2
  maxReplicaCount: 20
  triggers:
  - type: kafka
    metadata:
      bootstrapServers: kafka:9092
      consumerGroup: stt_workers_priority
      topic: stt_requests
      lagThreshold: '3'
  - type: prometheus
    metadata:
      serverAddress: http://prometheus:9090
      metricName: stt_processing_queue_size
      threshold: '5'
      query: stt_processing_queue_size
```

### 4. 연구 주제별 성능 최적화 전략

#### 🔬 연구 주제 1: "지능형 리소스 할당 최적화"

**실험 설계:**
1. **기준선 측정**: 현재 Docker Compose 환경
   - 10분 동영상 처리 시간: 4-5분
   - 메모리 사용률: 14.74% (905MB/6GB)
   - CPU 활용률: 평균 30-40%

2. **K8s 환경별 비교 실험**:
   ```yaml
   # 실험 A: 단일 Pod + VPA
   resources:
     requests: { cpu: 500m, memory: 1Gi }
     limits: { cpu: 8, memory: 12Gi }

   # 실험 B: 다중 Pod + HPA
   replicas: 1-5 (동적)
   resources:
     requests: { cpu: 1, memory: 2Gi }
     limits: { cpu: 2, memory: 4Gi }

   # 실험 C: 하이브리드 (VPA + HPA)
   minReplicas: 2, maxReplicas: 8
   resources: VPA 동적 조정
   ```

#### 🚀 연구 주제 2: "Event-Driven 스케일링 지연시간 최적화"

**메트릭 수집 계획:**
```yaml
# Prometheus 메트릭 정의
- name: kafka_consumer_lag_seconds
  help: Kafka 컨슈머 지연 시간
  type: gauge

- name: whisper_model_allocation_time
  help: Whisper 모델 할당 시간
  type: histogram

- name: stt_processing_duration_seconds
  help: STT 처리 소요 시간
  type: histogram
  labels: [model_size, audio_duration, concurrent_tasks]

- name: pod_scale_up_duration_seconds
  help: Pod 스케일업 소요 시간
  type: histogram
```

**성능 비교 실험:**
1. **Kafka 지연시간 기반 스케일링**
   - Lag Threshold: 1, 3, 5, 10 메시지
   - 스케일업 시간 vs 처리량 트레이드오프

2. **예측적 스케일링**
   ```python
   # Custom KEDA Scaler 구현
   def predict_scaling_need(kafka_metrics, time_series_data):
       # 시간대별 패턴 분석
       # YouTube 업로드 피크 시간 예측
       # 선제적 Pod 준비
   ```

#### 💰 연구 주제 3: "비용-성능 최적화"

**리소스 비용 모델링:**
```python
# 시간당 비용 계산
cost_per_hour = {
    'cpu_core': 0.05,      # $0.05/core/hour
    'memory_gb': 0.01,     # $0.01/GB/hour
    'storage_gb': 0.001    # $0.001/GB/hour
}

# Gemini API 비용
api_costs = {
    'gemini_flash': 0.000003,   # $0.000003/token
    'gemini_pro': 0.000024      # $0.000024/token
}
```

**실험 시나리오:**
- **시나리오 A**: 낮은 지연시간 우선 (항상 warm Pod 유지)
- **시나리오 B**: 비용 효율성 우선 (aggressive 스케일다운)
- **시나리오 C**: 적응적 전략 (시간대별 다른 임계값)

### 5. 구체적 실험 계획 및 로드맵

#### 📅 Phase 1: 기준선 구축 (2주)
```bash
# 현재 환경 성능 측정
1. Docker Compose 환경 벤치마크
   - 다양한 길이 동영상 (1분, 5분, 10분, 30분)
   - 동시 요청 처리 (1개, 3개, 5개)
   - 리소스 사용률 모니터링

2. Minikube 환경 구축
   minikube start --cpus=8 --memory=16384 --driver=docker
   kubectl apply -f k8s/basic-deployment.yaml
```

#### 📅 Phase 2: 기본 K8s 마이그레이션 (3주)
```yaml
# kompose로 초기 변환
kompose convert -f docker-compose.yml

# 수동 최적화
- ConfigMap/Secret 분리
- PVC 설정
- Service/Ingress 구성
- HealthCheck 적용
```

#### 📅 Phase 3: 고급 스케일링 실험 (4주)
```bash
# KEDA 설치 및 설정
kubectl apply -f https://github.com/kedacore/keda/releases/download/v2.12.0/keda-2.12.0.yaml

# Prometheus 스택 설치
helm install prometheus prometheus-community/kube-prometheus-stack

# 실험 자동화 스크립트
python3 k8s_experiments/run_scaling_experiments.py
```

#### 📅 Phase 4: 논문 데이터 수집 (3주)
```python
# 성능 데이터 수집 자동화
collect_metrics = [
    'processing_latency',
    'resource_utilization',
    'scaling_response_time',
    'cost_per_processed_minute',
    'quality_metrics'
]
```

### 6. 예상 연구 성과 및 기여도

#### 🎯 정량적 성과 목표
- **처리량 개선**: 30-50% 향상
- **리소스 효율성**: 40-60% 개선
- **응답시간**: 지연시간 20-30% 단축
- **비용 효율성**: 25-40% 비용 절감

#### 📚 학술적 기여
1. **Event-Driven AI 워크로드 스케일링 패턴**: 실시간 STT/번역 파이프라인에 특화된 스케일링 전략
2. **모델 풀링 vs Pod 풀링 성능 비교**: AI 워크로드에서 컨테이너 오케스트레이션 최적화 연구
3. **비용-성능 트레이드오프 모델**: 클라우드 네이티브 AI 서비스의 경제성 분석

#### 🏗️ 실용적 가치
- **실제 프로덕션 환경**: YouTube 번역 서비스로 실용성 검증
- **오픈소스 기여**: KEDA Custom Scaler, Helm Charts 공개
- **Best Practice 가이드**: AI 워크로드 K8s 운영 가이드라인

### 7. 기술적 도전과제 및 해결방안

#### ⚠️ 주요 도전과제
1. **Whisper 모델 로딩 지연**: 60초 초기화 시간
2. **상태 저장 워크로드**: Kafka 오프셋 관리
3. **GPU 리소스 스케줄링**: 향후 대형 모델 지원

#### 💡 해결방안
```yaml
# 1. Init Container로 모델 pre-loading
initContainers:
- name: model-downloader
  image: whisper-model-downloader:latest
  volumeMounts:
  - name: model-cache
    mountPath: /models

# 2. StatefulSet으로 Kafka 오프셋 관리
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: stt-processor-stateful

# 3. Node Affinity로 GPU 노드 스케줄링
nodeAffinity:
  requiredDuringSchedulingIgnoredDuringExecution:
    nodeSelectorTerms:
    - matchExpressions:
      - key: accelerator
        operator: In
        values: ["nvidia-tesla-t4"]
```

---

## 결론

현재 시스템의 **Whisper 모델 풀링 전략**은 단일 노드 환경에서는 효율적이지만, **Kubernetes 환경에서는 Pod 레벨 스케일링**이 더 큰 유연성과 효율성을 제공할 것으로 예상됩니다.

특히 **Event-Driven 스케일링**과 **비용-성능 최적화**를 결합한 연구는 실시간 AI 파이프라인 운영에 실용적이고 혁신적인 기여를 할 수 있을 것입니다.