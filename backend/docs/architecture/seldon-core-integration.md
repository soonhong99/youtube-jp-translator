# Seldon Core 통합 설계

## 개요

ML 팀에서 개발한 번역 모델을 백엔드 시스템과 통합하기 위해 Seldon Core를 활용합니다. Seldon Core는 Kubernetes에서 ML 모델을 쉽게 배포하고 관리할 수 있게 해주는 오픈소스 플랫폼입니다.

## 통합 아키텍처

1. ML 팀은 번역 모델을 개발하고 학습한 후 모델 아티팩트를 제공
2. 백엔드 팀은 Seldon Core를 사용하여 이 모델을 배포
3. API 게이트웨이는 Seldon Core REST API를 통해 번역 모델과 통신

## 구현 단계

1. Kubernetes 클러스터에 Seldon Core 설치
2. ML 모델 컨테이너화 (ML 팀과 협업)
3. SeldonDeployment 리소스 정의 및 배포
4. API 게이트웨이에서 Seldon Core REST API 연동

## Seldon Core API 인터페이스

### 예상 요청 형식
```json
{
  "data": {
    "ndarray": ["일본어 텍스트 1", "일본어 텍스트 2"]
  }
}
```