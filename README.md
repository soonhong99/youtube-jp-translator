# YouTube 일본어 STT 및 번역 시스템

## 1. 프로젝트 개요

본 프로젝트는 YouTube 비디오 URL을 입력받아 해당 영상의 일본어 음성을 추출하고, Speech-to-Text(STT) 기술을 사용하여 텍스트로 변환하는 시스템입니다. 최종적으로는 변환된 일본어 텍스트를 한국어로 번역하는 기능을 목표로 합니다.

특히, 긴 영상 처리 시 발생할 수 있는 사용자 대기 시간 및 서버 부하 문제를 해결하기 위해 **Apache Kafka를 이용한 비동기(Asynchronous) 메시지 큐 방식**을 도입하여 시스템을 설계했습니다. 이를 통해 사용자는 요청 후 즉시 응답을 받고, 처리 진행 상황 및 결과를 **WebSocket을 통해 실시간**으로 확인할 수 있습니다.

현재까지 일본어 STT 기능 및 실시간 결과 확인을 위한 백엔드 파이프라인과 React 기반 프론트엔드 클라이언트가 구현되었습니다.

## 2. 시스템 아키텍처

![System Architecture Diagram](docs/architecture.png) ```mermaid
graph TD
    A[Browser / React Client] -- 1. POST /extract (URL) --> B(Youtube Extractor);
    B -- 2. Response (File Path) --> A;
    A -- 3. POST /request_transcription (File Path) --> C(STT API);
    C -- 4. Produce Request --> K_REQ[Kafka Topic: stt_requests];
    C -- 5. Response (Task ID) --> A;
    D(STT Worker) -- 6. Consume Request --> K_REQ;
    A -- 7. Connect WebSocket --> C;
    D -- 8. Process STT (Chunks) --> D;
    D -- 9. Produce Results/Progress --> K_RES[Kafka Topic: stt_results];
    E[API BG Consumer] -- 10. Consume Results --> K_RES;
    subgraph "STT API Service"
        C
        E
        F[WebSocket Manager]
        G[Redis History]
    end
    E -- 11. Forward to WS --> F;
    F -- 12. Push to Client --> A;
    E -- 13. Save to History --> G;
    subgraph "Client Connection"
      A --- F
    end
    subgraph "History Retrieval"
       C -.-> G
       G -.-> F
    end

    style K_REQ fill:#f9f,stroke:#333,stroke-width:2px
    style K_RES fill:#f9f,stroke:#333,stroke-width:2px
```

**주요 구성 요소:**

* **Frontend (`frontend`):** 사용자와 상호작용하는 React 기반 웹 애플리케이션. YouTube URL 입력, 상태/결과 표시, WebSocket 연결 관리.
* **Backend Services (`backend/services`):**
    * **`youtube-extractor`:** FastAPI 기반. YouTube URL로부터 음성 파일을 추출하여 서버 내 공유 볼륨에 WAV 파일로 저장하고 파일 경로 반환.
    * **`stt-processor-api`:** FastAPI 기반. 사용자 요청 접수, 고유 작업 ID(Task ID) 발급, Kafka `stt_requests` 토픽으로 작업 발행. WebSocket 연결 관리 및 Redis 히스토리 조회. 백그라운드에서 Kafka `stt_results` 토픽 구독하여 결과 수신 후 WebSocket 클라이언트에게 실시간 전송 및 Redis 히스토리 저장.
    * **`stt-processor-worker`:** Python 스크립트 (Kafka Consumer). `stt_requests` 토픽 구독하여 작업 수신. `pydub`으로 오디오 분할, `faster-whisper`로 STT 수행. 진행률 및 결과를 `stt_results` 토픽으로 발행.
* **Infrastructure (`backend/docker-compose.yml`):**
    * **`Kafka` + `Zookeeper`:** 비동기 메시지 큐 시스템. API 서버와 워커 간의 요청/결과 전달 담당, 서비스 간 의존성 분리.
    * **`Redis`:** 인메모리 데이터 저장소. WebSocket 메시지 히스토리를 임시 저장하여 늦게 연결된 클라이언트도 이전 메시지를 받을 수 있도록 지원.

## 3. 기술 스택 및 선택 이유

* **Backend:**
    * **Python:** 주요 개발 언어.
    * **FastAPI:** 높은 성능, 비동기 처리 지원, 쉬운 사용법으로 API 서버 및 WebSocket 서버 구축에 활용.
    * **Apache Kafka (`kafka-python`):** 대용량 메시지 처리, 시스템 확장성 및 안정성 확보, 서비스 간 느슨한 결합을 위해 비동기 메시지 큐로 선택.
    * **Redis (`redis-py`):** 빠른 인메모리 저장소로, WebSocket 메시지 히스토리를 효율적으로 관리하기 위해 사용.
    * **Faster-Whisper:** STT 모델로 선택 (정확도 및 효율성 고려).
    * **Pydub:** 오디오 파일 분할 등 처리를 위해 사용.
* **Frontend:**
    * **React:** 컴포넌트 기반 UI 구축 및 상태 관리에 널리 사용되는 JavaScript 라이브러리.
    * **JavaScript (ES6+):** 프론트엔드 로직 구현.
    * **WebSocket API (Browser):** 서버로부터 실시간 업데이트를 받기 위해 사용.
    * **Axios / Fetch API:** 백엔드 HTTP API 호출에 사용.
* **Infrastructure & Others:**
    * **Docker / Docker Compose:** 각 서비스를 컨테이너화하여 개발 및 배포 환경의 일관성 유지, 서비스 오케스트레이션 간소화.
    * **Git / GitHub:** 버전 관리 및 협업.

## 4. 주요 기능 (현재)

* YouTube URL 기반 일본어 오디오 추출.
* Kafka를 이용한 STT 작업 비동기 처리 요청.
* 오디오 자동 분할(Chunking) 및 청크 단위 STT 처리.
* WebSocket을 통한 실시간 STT 진행률 및 결과(타임스탬프 포함 텍스트 세그먼트) 전송.
* Redis를 이용한 메시지 히스토리 제공 (WebSocket 재연결/늦은 연결 시).
* React 기반 웹 인터페이스 제공.

## 5. 설치 및 실행 방법

**사전 요구 사항:**

* [Docker](https://www.docker.com/products/docker-desktop/) 설치
* [Docker Compose](https://docs.docker.com/compose/install/) 설치 (Docker Desktop에 포함)
* [Node.js](https://nodejs.org/) 및 [npm](https://www.npmjs.com/)/[yarn](https://yarnpkg.com/) 설치 (Frontend 실행용)

**실행 순서:**

1.  **백엔드 서비스 실행:**
    * 프로젝트 루트의 `backend` 디렉토리로 이동합니다.
        ```bash
        cd backend
        ```
    * **(최초 실행 시 또는 변경사항 있을 시 권장)** Docker 이미지를 빌드합니다. (시간이 소요될 수 있습니다.)
        ```bash
        docker-compose build
        ```
    * Docker Compose를 사용하여 모든 백엔드 서비스(Extractor, API, Worker, Kafka, Zookeeper, Redis)를 백그라운드에서 시작합니다.
        ```bash
        docker-compose up -d
        ```
    * 로그 확인 (선택 사항): `docker-compose logs -f`

2.  **프론트엔드 애플리케이션 실행:**
    * 프로젝트 루트의 `frontend` 디렉토리로 이동합니다.
        ```bash
        # 현재 위치가 backend라면:
        cd ../frontend
        # 프로젝트 루트에서 시작한다면:
        # cd frontend
        ```
    * **(최초 실행 시)** 필요한 npm 패키지를 설치합니다.
        ```bash
        npm install
        # 또는 yarn install
        ```
    * **(선택 사항)** 프로젝트 루트(`frontend`)에 `.env` 파일을 생성하고 백엔드 API 주소를 설정합니다. (기본값은 코드에 포함됨)
        ```
        REACT_APP_EXTRACTOR_API_URL=[http://127.0.0.1:8000](http://127.0.0.1:8000)
        REACT_APP_STT_API_URL=[http://127.0.0.1:8001](http://127.0.0.1:8001)
        REACT_APP_WS_BASE_URL=ws://127.0.0.1:8001
        ```
    * React 개발 서버를 시작합니다.
        ```bash
        npm start
        # 또는 yarn start
        ```

3.  **애플리케이션 접속:**
    * 웹 브라우저를 열고 `http://localhost:3000` 주소로 접속합니다.
    * YouTube URL을 입력하고 "Start Transcription" 버튼을 눌러 사용합니다.

## 6. 향후 계획: 번역 모델 서빙 (Seldon Core)

현재 STT 기능 구현에 이어, 최종 목표인 **일본어 -> 한국어 번역 기능**을 추가할 계획입니다. 이때, 훈련되거나 선택된 번역 모델을 실제 서비스 환경에서 효율적으로 운영하기 위해 **Seldon Core**를 이용한 **모델 서빙 전략**을 채택할 예정입니다.

**Seldon Core 도입 계획:**

1.  **번역 모델 준비:** 일본어-한국어 번역 모델을 선택하거나 Fine-tuning 합니다. (Colab 등 활용 가능)
2.  **Python Wrapper 클래스 작성:** Seldon Core가 모델을 로드하고 예측 요청(`predict`)을 처리하는 방법을 정의하는 Python 클래스를 작성합니다. (`transformers` 라이브러리 사용 로직 포함)
3.  **모델 아티팩트 관리:** 번역 모델 파일들을 GCS, S3 등 클라우드 스토리지 또는 쿠버네티스 PV에 저장합니다.
4.  **추론 서버 Docker 이미지 빌드:** Python Wrapper 클래스와 `requirements.txt` (필요 라이브러리 명시)를 기반으로 추론 서버 역할을 할 Docker 이미지를 빌드합니다. (Seldon Core의 `s2i` 도구 활용 가능)
5.  **쿠버네티스(Kubernetes) 환경 준비:** 모델을 서빙할 쿠버네티스 클러스터를 준비합니다. (GKE, EKS, AKS 등 또는 로컬 테스트용 Minikube/Kind)
6.  **Seldon Core 설치:** 준비된 쿠버네티스 클러스터에 Seldon Core를 설치합니다.
7.  **SeldonDeployment 배포:** 모델 서빙 설정을 정의하는 `SeldonDeployment` YAML 파일을 작성합니다. 이 파일에는 사용할 Docker 이미지, 모델 아티팩트 위치, 리소스 요구사항(CPU/GPU), API 엔드포인트 타입(REST/gRPC) 등이 명시됩니다.
8.  `kubectl apply` 명령어를 사용하여 쿠버네티스에 `SeldonDeployment`를 배포합니다.

**Seldon Core 선택 이유:**

* **확장성:** 트래픽에 따라 모델 서빙 인스턴스를 자동으로 확장할 수 있습니다.
* **고급 배포 전략:** A/B 테스트, 카나리 배포 등을 통해 안정적인 모델 업데이트가 가능합니다.
* **모니터링 및 로깅:** 모델 서빙 성능 및 요청/응답에 대한 풍부한 메트릭과 로깅을 제공합니다.
* **표준화:** MLOps 파이프라인에서 모델 서빙을 위한 표준적이고 강력한 방법을 제공합니다.

---
