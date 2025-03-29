# 일본어 구어체 번역 유튜브 스크립트 생성 서비스 (백엔드)

유튜브 동영상의 일본어 구어체를 자연스러운 한국어로 번역하는 서비스의 백엔드 레포지토리입니다.

## 개요

본 서비스는 유튜브 URL을 입력받아 다음과 같은 과정을 거쳐 번역 스크립트를 생성합니다:
1. 유튜브 동영상에서 오디오 추출
2. STT(Speech-to-Text) 모델을 이용한 일본어 텍스트 변환
3. 구어체 특화 모델을 통한 한국어 번역
4. 사용자에게 자연스러운 번역 스크립트 제공

## 아키텍처

- 마이크로서비스 아키텍처 기반 설계
- Apache Kafka를 통한 비동기 처리
- GraphQL API
- Seldon Core를 활용한 번역 모델 서빙

## 서비스 구성

- youtube-extractor: 유튜브 동영상에서 오디오 추출
- stt-service: Faster Whisper 모델을 활용한 음성-텍스트 변환
- api-gateway: GraphQL API 및 클라이언트 통신 관리

## 설치 및 실행 방법

### 요구사항
- Docker
- Docker Compose
- Python 3.8+

### 개발 환경 설정
```bash
# 레포지토리 클론
git clone https://github.com/soonhong99/youtube-jp-translator.git
cd backend

# 가상환경 설정
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 개발 환경 실행
docker-compose up -d