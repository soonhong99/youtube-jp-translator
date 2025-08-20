# AI Orchestrator 시스템 가이드

## 🎯 개요

AI Orchestrator는 Gemini 2.5 Pro와 LangChain을 활용한 고급 AI 워크플로우 관리 시스템입니다. 번역, 요약, 포맷팅, 품질 검토 등의 AI 작업을 통합적으로 관리합니다.

## 🏗️ 아키텍처

### 서비스 구조
```
AI Orchestrator
├── API Server (포트 8002)
├── Kafka Worker  
├── 4개 AI 에이전트
├── 3개 체인 워크플로우
└── 마스터 오케스트레이션
```

### AI 에이전트들
1. **TranslatorAgent**: 일본어→한국어 번역
2. **SummarizerAgent**: 콘텐츠 요약 및 키워드 추출  
3. **FormatterAgent**: 자막 포맷팅 및 화자 인식
4. **ReviewerAgent**: 번역 품질 검증 및 개선

### 워크플로우 체인들
1. **TranslationChain**: 번역 + 검토 + 개선
2. **PostProcessingChain**: 요약 + 포맷팅 + 메타데이터
3. **MasterChain**: 전체 오케스트레이션 + 조건부 분기

## 🚀 처리 모드

### Fast Mode (빠른 처리)
- 번역만 수행
- 약 30초 소요

### Standard Mode (표준 처리) 
- 번역 + 기본 후처리
- 요약, 포맷팅 포함
- 약 60초 소요

### Premium Mode (프리미엄 처리)
- 전체 기능 활성화
- 번역 검토, 개선, 하이라이트 추출
- 화자 인식, 가독성 향상
- 약 120초 소요

### Custom Mode (사용자 정의)
- 필요한 기능만 선택적 활성화

## 📡 API 엔드포인트

### 기본 엔드포인트
```bash
# 헬스체크
GET /health

# 에이전트 상태 확인
GET /agents/status

# 처리 모드 조회
GET /processing-modes
```

### 처리 엔드포인트
```bash
# 통합 처리 (권장)
POST /process
{
  "task_id": "uuid",
  "segments": [...],
  "mode": "premium",
  "options": {...}
}

# 레거시 번역 (하위 호환성)
POST /translate

# 배치 처리
POST /process/batch
```

## 🔧 환경 설정

### 필수 환경변수
```bash
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-1.5-pro-latest
GEMINI_TEMPERATURE=0.3
```

### 선택적 환경변수
```bash
MAX_CONCURRENT_TASKS=5
TRANSLATION_CACHE_TTL=3600
LANGCHAIN_TRACING_V2=true
```

## 🐳 Docker 사용법

### 개발 환경 시작
```bash
cd backend
docker-compose up -d
```

### AI 로그 확인
```bash
# API 서버 로그
docker-compose logs -f ai-orchestrator-api

# 워커 로그  
docker-compose logs -f ai-orchestrator-worker
```

## 📊 사용 예제

### 기본 번역 요청
```python
import requests

response = requests.post(
    "http://localhost:8080/api/ai/process",
    json={
        "task_id": "test-123",
        "segments": [
            {
                "start": 0.0,
                "end": 3.5,
                "text": "こんにちは、今日はいい天気ですね。"
            }
        ],
        "mode": "standard"
    }
)

result = response.json()
print(result["segments"][0]["korean_text"])  # "안녕하세요, 오늘은 날씨가 좋네요."
```

### 프리미엄 처리 (전체 기능)
```python
response = requests.post(
    "http://localhost:8080/api/ai/process", 
    json={
        "task_id": "premium-test",
        "segments": segments,
        "mode": "premium",
        "options": {
            "highlight_count": 5,
            "max_chars_per_line": 35,
            "parallel_processing": True
        }
    }
)

result = response.json()
metadata = result["metadata"]

# 요약 정보
summary = metadata["summary"]
print(f"요약: {summary['summary']}")
print(f"키워드: {summary['keywords']}")

# 화자 정보
speaker_analysis = metadata["speaker_analysis"]
print(f"감지된 화자 수: {speaker_analysis['total_speakers']}")

# 하이라이트
highlights = metadata["highlights"]
for i, highlight in enumerate(highlights):
    print(f"하이라이트 {i+1}: {highlight['korean_text']}")
```

## 🎛️ 커스텀 워크플로우

```python
# 번역 + 요약만
custom_options = {
    "enable_translation": True,
    "enable_review": False,
    "enable_post_processing": True,
    "enable_summary": True,
    "enable_formatting": False,
    "enable_highlights": False
}

response = requests.post(
    "http://localhost:8080/api/ai/process",
    json={
        "mode": "custom",
        "options": custom_options,
        "segments": segments
    }
)
```

## 📈 성능 최적화

### 병렬 처리 활성화
```json
{
  "mode": "premium",
  "options": {
    "parallel_processing": true,
    "max_concurrent_tasks": 3
  }
}
```

### 캐싱 활용
- 번역 결과는 Redis에 자동 캐싱
- TTL: 1시간 (설정 가능)

## 🔍 모니터링

### 에이전트 상태
```bash
curl http://localhost:8080/api/ai/agents/status
```

### 처리 통계
```bash
# 응답의 metadata.statistics에서 확인
{
  "translation_success_rate": 0.95,
  "enhancement_rate": 0.80,
  "processing_time": 45.2
}
```

## 🚨 에러 처리

### 자동 Fallback
```python
# Premium 실패 시 Standard → Fast 순으로 자동 시도
response = requests.post("/process", json={
    "mode": "premium",
    "options": {"enable_fallback": True}
})
```

### 에러 응답 형식
```json
{
  "task_id": "xxx",
  "status": "failed", 
  "error": "Processing failed: Model not available",
  "metadata": {
    "attempted_modes": ["premium", "standard", "fast"],
    "failed_at": "translation_step"
  }
}
```

## 🔧 개발자 가이드

### 새 에이전트 추가
1. `src/agents/` 에 새 에이전트 클래스 생성
2. `MasterChain`에 에이전트 등록
3. 필요한 체인에 통합

### 커스텀 체인 생성
1. `src/chains/` 에 새 체인 클래스 생성
2. LangChain Runnable 인터페이스 구현
3. `MasterChain`에서 호출

## 📝 주요 개선사항

✅ **Gemini 2.5 Pro 지원**: 최신 모델로 번역 품질 향상  
✅ **LangChain 통합**: 복잡한 워크플로우 관리  
✅ **병렬 처리**: 처리 시간 단축  
✅ **화자 인식**: 대화형 콘텐츠 지원  
✅ **품질 검증**: 자동 번역 검토 및 개선  
✅ **유연한 모드**: 용도에 맞는 처리 선택  
✅ **확장 가능**: 새 AI 기능 쉽게 추가

## 📞 지원

문의사항이나 버그 리포트는 프로젝트 GitHub 이슈에 등록해 주세요.