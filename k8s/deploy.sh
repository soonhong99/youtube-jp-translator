#!/bin/bash

# YouTube Japanese Translator Kubernetes Deployment Script
# 단계별 배포 및 검증 스크립트

set -e  # 에러 발생 시 즉시 종료

# 색상 출력을 위한 함수
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 전역 변수
NAMESPACE="youtube-translator"
TIMEOUT=300s
KIND_CLUSTER_NAME=${KIND_CLUSTER_NAME:-kind}

# kubectl 명령어 확인
check_prerequisites() {
    log_info "전제 조건 확인 중..."

    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl이 설치되어 있지 않습니다."
        exit 1
    fi

    if ! kubectl cluster-info &> /dev/null; then
        log_error "Kubernetes 클러스터에 연결할 수 없습니다."
        exit 1
    fi

    if ! command -v docker &> /dev/null; then
        log_warning "docker가 없어 로컬 이미지 빌드를 건너뜁니다. 사전에 이미지를 레지스트리에 push 했는지 확인하세요."
    fi

    if ! command -v kind &> /dev/null; then
        log_warning "kind 명령어가 없어 로컬 이미지를 클러스터로 로드하지 못합니다."
    fi

    log_success "전제 조건 확인 완료"
}

# 네임스페이스 생성
create_namespace() {
    log_info "네임스페이스 생성 중..."
    kubectl apply -f namespace.yaml
    log_success "네임스페이스 생성 완료"
}

# ConfigMap 및 Secret 배포
deploy_configs() {
    log_info "ConfigMap 및 Secret 배포 중..."

    # ConfigMap 배포
    kubectl apply -f configmaps.yaml

    # Secret 배포 (실제 환경에서는 수동으로 생성 권장)
    log_warning "Secret 파일에 실제 API 키를 설정했는지 확인하세요"
    kubectl apply -f secrets.yaml

    log_success "ConfigMap 및 Secret 배포 완료"
}

build_and_load_stt_image() {
    if ! command -v docker &> /dev/null; then
        log_warning "docker 미설치 - STT 이미지 빌드 단계를 건너뜁니다"
        return
    fi

    log_info "STT Processor Docker 이미지 빌드 중..."
    pushd ../backend/services/stt-processor > /dev/null
    docker build -t stt-processor:latest .
    popd > /dev/null

    if command -v kind &> /dev/null; then
        if kind get clusters | grep -qx "${KIND_CLUSTER_NAME}"; then
            log_info "Kind 클러스터(${KIND_CLUSTER_NAME})에 stt-processor 이미지를 로드합니다"
            kind load docker-image stt-processor:latest --name "${KIND_CLUSTER_NAME}"
        else:
            log_warning "Kind 클러스터 ${KIND_CLUSTER_NAME}를 찾지 못했습니다. 이미지를 수동으로 로드하세요."
        fi
    else:
        log_warning "kind 명령어를 찾을 수 없습니다 - 이미지 로드는 생략됩니다"
    fi

    log_success "STT Processor 이미지 준비 완료"
}

# 스토리지 배포
deploy_storage() {
    log_info "스토리지 리소스 배포 중..."
    kubectl apply -f storage.yaml
    log_success "스토리지 리소스 배포 완료"
}

# Zookeeper 배포 및 대기
deploy_zookeeper() {
    log_info "Zookeeper 배포 중..."
    kubectl apply -f zookeeper-statefulset.yaml

    log_info "Zookeeper 준비 상태 대기 중..."
    kubectl wait --for=condition=ready pod -l app=zookeeper -n $NAMESPACE --timeout=$TIMEOUT

    log_success "Zookeeper 배포 완료"
}

# Kafka 배포 및 대기
deploy_kafka() {
    log_info "Kafka 배포 중..."
    kubectl apply -f kafka-statefulset.yaml

    log_info "Kafka 준비 상태 대기 중..."
    kubectl wait --for=condition=ready pod -l app=kafka -n $NAMESPACE --timeout=$TIMEOUT

    # Kafka 토픽 생성
    create_kafka_topics

    log_success "Kafka 배포 완료"
}

# Kafka 토픽 생성
create_kafka_topics() {
    log_info "Kafka 토픽 생성 중..."

    # Kafka pod 이름 가져오기
    KAFKA_POD=$(kubectl get pod -l app=kafka -n $NAMESPACE -o jsonpath='{.items[0].metadata.name}')

    # 토픽 생성 명령어들
    TOPICS=(
        "stt_requests"
        "stt_results"
        "ai_processing_requests"
        "ai_processing_results"
        "stt_chunks"
        "translation_queue"
        "realtime_results"
        "performance_metrics"
        "streaming_control"
        "streaming_requests"
        "buffering_requests"
        "intelligent_translation_requests"
        "optimized_translation_results"
        "system_alerts"
    )

    for topic in "${TOPICS[@]}"; do
        kubectl exec -n $NAMESPACE $KAFKA_POD -- kafka-topics \
            --create --if-not-exists \
            --topic $topic \
            --bootstrap-server localhost:9092 \
            --partitions 3 \
            --replication-factor 3 || true
    done

    log_success "Kafka 토픽 생성 완료"
}

# Redis 배포
deploy_redis() {
    log_info "Redis 배포 중..."
    kubectl apply -f redis-deployment.yaml

    log_info "Redis 준비 상태 대기 중..."
    kubectl wait --for=condition=ready pod -l app=redis -n $NAMESPACE --timeout=$TIMEOUT

    log_success "Redis 배포 완료"
}

# STT Processor 배포
deploy_stt_processor() {
    build_and_load_stt_image
    log_info "STT Processor 배포 중..."
    kubectl apply -f stt-processor-deployment.yaml

    log_info "STT Processor 준비 상태 대기 중..."
    kubectl wait --for=condition=ready pod -l app=stt-processor-api -n $NAMESPACE --timeout=$TIMEOUT
    kubectl wait --for=condition=ready pod -l app=stt-processor-worker -n $NAMESPACE --timeout=$TIMEOUT

    log_success "STT Processor 배포 완료"
}

# AI Orchestrator 배포
deploy_ai_orchestrator() {
    log_info "AI Orchestrator 배포 중..."
    kubectl apply -f ai-orchestrator-deployment.yaml

    log_info "AI Orchestrator 준비 상태 대기 중..."
    kubectl wait --for=condition=ready pod -l app=ai-orchestrator-api -n $NAMESPACE --timeout=$TIMEOUT
    kubectl wait --for=condition=ready pod -l app=ai-orchestrator-worker -n $NAMESPACE --timeout=$TIMEOUT

    log_success "AI Orchestrator 배포 완료"
}

# API Gateway 및 기타 서비스 배포
deploy_api_gateway() {
    log_info "API Gateway 및 관련 서비스 배포 중..."
    kubectl apply -f api-gateway-deployment.yaml

    log_info "API Gateway 준비 상태 대기 중..."
    kubectl wait --for=condition=ready pod -l app=api-gateway -n $NAMESPACE --timeout=$TIMEOUT
    kubectl wait --for=condition=ready pod -l app=youtube-extractor -n $NAMESPACE --timeout=$TIMEOUT

    log_success "API Gateway 배포 완료"
}

# 모니터링 스택 배포 (선택사항)
deploy_monitoring() {
    log_info "모니터링 스택 배포 중..."
    kubectl apply -f monitoring.yaml

    log_info "모니터링 서비스 준비 상태 대기 중..."
    kubectl wait --for=condition=ready pod -l app=prometheus -n $NAMESPACE --timeout=$TIMEOUT || true
    kubectl wait --for=condition=ready pod -l app=grafana -n $NAMESPACE --timeout=$TIMEOUT || true

    log_success "모니터링 스택 배포 완료"
}

# 배포 상태 확인
check_deployment_status() {
    log_info "배포 상태 확인 중..."

    echo "=== Pod 상태 ==="
    kubectl get pods -n $NAMESPACE -o wide

    echo ""
    echo "=== Service 상태 ==="
    kubectl get services -n $NAMESPACE

    echo ""
    echo "=== PVC 상태 ==="
    kubectl get pvc -n $NAMESPACE

    echo ""
    echo "=== HPA 상태 ==="
    kubectl get hpa -n $NAMESPACE || true

    log_success "배포 상태 확인 완료"
}

# 배포 테스트
test_deployment() {
    log_info "배포 테스트 실행 중..."

    # API Gateway 헬스체크
    log_info "API Gateway 헬스체크..."
    kubectl exec -n $NAMESPACE deploy/api-gateway -- curl -f http://localhost:8080/health || log_warning "API Gateway 헬스체크 실패"

    # STT Processor API 헬스체크
    log_info "STT Processor API 헬스체크..."
    kubectl exec -n $NAMESPACE deploy/stt-processor-api -- curl -f http://localhost:8001/health || log_warning "STT Processor API 헬스체크 실패"

    # AI Orchestrator API 헬스체크
    log_info "AI Orchestrator API 헬스체크..."
    kubectl exec -n $NAMESPACE deploy/ai-orchestrator-api -- curl -f http://localhost:8002/health || log_warning "AI Orchestrator API 헬스체크 실패"

    log_success "배포 테스트 완료"
}

# 외부 접근 정보 출력
show_access_info() {
    log_info "외부 접근 정보:"

    # LoadBalancer 서비스 IP 확인
    EXTERNAL_IP=$(kubectl get service api-gateway-service -n $NAMESPACE -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "Pending")

    if [ "$EXTERNAL_IP" = "Pending" ] || [ -z "$EXTERNAL_IP" ]; then
        log_warning "LoadBalancer IP가 아직 할당되지 않았습니다."
        log_info "포트 포워딩을 사용하세요:"
        echo "kubectl port-forward service/api-gateway-service -n $NAMESPACE 8080:8080"
    else
        log_success "API Gateway 접근 주소: http://$EXTERNAL_IP:8080"
    fi

    # 모니터링 서비스 접근 정보
    echo ""
    log_info "모니터링 서비스 접근 (포트 포워딩 필요):"
    echo "Prometheus: kubectl port-forward service/prometheus-service -n $NAMESPACE 9090:9090"
    echo "Grafana: kubectl port-forward service/grafana-service -n $NAMESPACE 3000:3000"
}

# 메인 배포 함수
main() {
    log_info "YouTube Japanese Translator Kubernetes 배포 시작"

    # 인자 파싱
    DEPLOY_MONITORING=false
    SKIP_TESTS=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            --monitoring)
                DEPLOY_MONITORING=true
                shift
                ;;
            --skip-tests)
                SKIP_TESTS=true
                shift
                ;;
            -h|--help)
                echo "사용법: $0 [옵션]"
                echo "옵션:"
                echo "  --monitoring    모니터링 스택도 함께 배포"
                echo "  --skip-tests    배포 테스트 생략"
                echo "  -h, --help      이 도움말 출력"
                exit 0
                ;;
            *)
                log_error "알 수 없는 옵션: $1"
                exit 1
                ;;
        esac
    done

    # 단계별 배포 실행
    check_prerequisites
    create_namespace
    deploy_configs
    deploy_storage

    log_info "=== Phase 1: 인프라 서비스 배포 ==="
    deploy_zookeeper
    deploy_kafka
    deploy_redis

    log_info "=== Phase 2: 핵심 애플리케이션 배포 ==="
    deploy_stt_processor
    deploy_ai_orchestrator
    deploy_api_gateway

    if [ "$DEPLOY_MONITORING" = true ]; then
        log_info "=== Phase 3: 모니터링 스택 배포 ==="
        deploy_monitoring
    fi

    log_info "=== Phase 4: 배포 검증 ==="
    check_deployment_status

    if [ "$SKIP_TESTS" = false ]; then
        test_deployment
    fi

    show_access_info

    log_success "YouTube Japanese Translator Kubernetes 배포 완료!"
    log_info "시스템이 완전히 준비되기까지 몇 분 정도 소요될 수 있습니다."
}

# 스크립트 실행
main "$@"