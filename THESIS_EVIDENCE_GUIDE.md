# 📋 논문 설계 검증 증거 수집 가이드

> **YouTube Japanese STT & AI Translation System** 설계 검증을 위한 실제 증거 수집 방법

---

## 🎯 목적
이 가이드는 논문 3장 설계 부분의 다음 주장들을 뒷받침하는 실제 증거들을 어디서 어떻게 확인할 수 있는지 안내합니다:

1. **마이크로서비스 아키텍처**: 'AI 번역팀'을 위한 가상의 오피스
2. **실시간 진행률 피드백**: 투명한 처리 과정 제공  
3. **원문-번역문 병렬 제공**: 정확한 의도 이해를 위한 UI
4. **영상 동기화 인터랙티브 UI**: 완벽한 몰입 경험
5. **AI 에이전트 협업 과정**: 4단계 전문가 시스템

---

## 🏗️ 1. 마이크로서비스 아키텍처 증거

### 📍 **확인 위치**
```bash
# 파일 위치
backend/docker-compose.yml  # 라인 104-306

# 실행 명령어 (터미널)
cd backend
docker-compose ps
```

### 📸 **수집 가능한 증거**

**1) 서비스 독립성 증명**
```bash
docker-compose ps
```
**예상 출력 (스크린샷 촬영용):**
```
NAME                     IMAGE                    COMMAND                  SERVICE               CREATED          STATUS                    PORTS
api-gateway              backend-api-gateway      "uvicorn src.main:app"   api-gateway           2 minutes ago    Up 2 minutes              0.0.0.0:8080->8080/tcp
youtube-extractor        backend-youtube-extract  "uvicorn main:app --h"   youtube-extractor     2 minutes ago    Up 2 minutes              
stt-processor-api        backend-stt-processor    "uvicorn src.main:app"   stt-processor-api     2 minutes ago    Up 2 minutes              
ai-orchestrator-api      backend-ai-orchestrator  "uvicorn src.main:app"   ai-orchestrator-api   2 minutes ago    Up 2 minutes              
```

**2) 서비스 헬스체크 상태**
```bash
# 각 서비스별 상태 확인
curl http://localhost:8080/health  # API Gateway
curl http://localhost:8080/api/youtube/health  # YouTube Extractor (프록시)
curl http://localhost:8080/api/stt/health      # STT Processor (프록시)  
curl http://localhost:8080/api/ai/agents/status # AI Orchestrator (프록시)
```

**3) 네트워크 독립성 증명**
```bash
docker network ls | grep backend
docker network inspect backend_backend-network
```

---

## 📊 2. 실시간 진행률 피드백 증거

### 📍 **확인 위치**
```bash
# UI 코드 위치
frontend/src/components/StatusBar.js          # 라인 14-22 (진행률 바)
frontend/src/pages/TranslateResult.js         # 라인 433-500 (WebSocket 처리)

# 백엔드 WebSocket 프록시
backend/services/api-gateway/src/main.py      # 라인 191-243
```

### 📸 **수집 가능한 증거**

**1) 실시간 UI 업데이트 (브라우저 스크린샷)**
- **URL**: `http://localhost:3000`
- YouTube URL 입력 → 처리 중 화면에서 다음 요소들 캡처:
  ```
  📊 진행 상태
  오디오 추출 중... [||||||||||||     ] 67%
  ```

**2) WebSocket 메시지 로그 (개발자 도구)**
- **브라우저 개발자 도구** → **Network** → **WS** 탭
- 실시간 메시지 확인:
  ```json
  {
    "status": "STT 처리 중...",
    "progress": 45,
    "data": [...] 
  }
  ```

**3) 백엔드 실시간 로그**
```bash
docker-compose logs -f api-gateway | grep -i websocket
docker-compose logs -f stt-processor-api | grep -i progress
```

---

## 🔄 3. 원문-번역문 병렬 제공 증거

### 📍 **확인 위치**
```bash
# UI 구현 코드
frontend/src/pages/TranslateResult.js         # 라인 646-684
```

### 📸 **수집 가능한 증거**

**1) 병렬 표시 UI 스크린샷**
- **URL**: `http://localhost:3000` → 번역 완료 후
- 다음과 같은 형태로 표시되는 화면 캡처:
  ```
  [00:15 - 00:18]
  JP: こんにちは、皆さん。今日は素晴らしい天気ですね。 🔊
  KO: 안녕하세요, 여러분. 오늘은 정말 좋은 날씨네요.
  ```

**2) 코드 레벨 증거**
```javascript
// TranslateResult.js 라인 646-684
{/* 일본어 원문 + TTS 버튼 */}
<strong className="text-sky-400">JP:</strong>&nbsp;{seg.text}

{/* 한국어 번역 */}
<strong className="text-green-300">KO:</strong> {seg.korean_text}
```

---

## 🎬 4. 영상 동기화 인터랙티브 UI 증거

### 📍 **확인 위치**
```bash
# 자동 하이라이트 구현
frontend/src/pages/TranslateResult.js         # 라인 345-363

# 자동 스크롤 복원 기능  
frontend/src/pages/TranslateResult.js         # 라인 527-541
```

### 📸 **수집 가능한 증거**

**1) 자동 하이라이트 동작 (동영상 녹화 권장)**
- YouTube 영상 재생 중 현재 구간 자막이 흰색 배경으로 하이라이트
- 영상 시간과 자막 구간이 정확히 동기화

**2) 자동 스크롤 기능**
- 긴 자막에서 현재 재생 구간으로 자동 스크롤
- 사용자가 수동 스크롤 시 "현재위치로 이동" 버튼 표시

**3) 코드 레벨 증거**
```javascript
// 자동 하이라이트 로직 (라인 345-363)
const currentSegment = segments.find(
  (seg) => currentTime >= seg.start && currentTime <= seg.end
);
if (currentSegment && activeIndex !== currentSegment.start) {
  setActiveIndex(currentSegment.start);
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
```

---

## 🤖 5. AI 에이전트 협업 과정 증거

### 📍 **확인 위치**
```bash
# AI 모니터링 UI
frontend/src/components/AiAgentMonitor.js     # 전체 파일
frontend/src/components/AiModeSelector.js     # AI 모드 선택 UI

# 백엔드 AI 처리
backend/services/ai-orchestrator/src/        # AI 에이전트 시스템
```

### 📸 **수집 가능한 증거**

**1) AI 모드 선택 UI**
- **URL**: `http://localhost:3000` 
- 첫 화면에서 4가지 모드 선택 카드:
  ```
  ⚡ 빠른 모드     🎯 표준 모드
  ~30초, 약 4원   ~60초, 약 15원
  
  ✨ 프리미엄 모드  🔧 커스텀 모드  
  ~120초, 약 30원  가변적, 설정에 따라
  ```

**2) AI 에이전트 협업 모니터**
- 번역 처리 중 다음과 같은 UI가 표시:
  ```
  🤖 AI 에이전트 처리 현황 (standard 모드)
  
  🌐 TranslatorAgent        ✅ 완료
  일본어 → 한국어 번역
  
  📝 SummarizerAgent        ⚡ 처리 중 [████████░░] 80%
  내용 요약 및 키워드 추출
  
  ✨ FormatterAgent         ⏳ 대기 중
  자막 서식 개선
  ```

**3) 처리 성능 요약**
```
총 처리 시간: 45초    토큰 사용량: 1,247
예상 비용: 15원      사용 모델: Gemini-1.5-Flash
```

---

## 📈 6. 시스템 모니터링 대시보드 증거 (논문 검증용)

### 📍 **확인 위치**
```bash
# 모니터링 대시보드 UI
frontend/src/components/SystemMonitorDashboard.js  # 전체 파일

# 백엔드 메트릭 API
backend/services/api-gateway/src/main.py           # 라인 252-427
```

### 📸 **수집 가능한 증거**

**1) 데이터 흐름 추적**
```
🔄 데이터 흐름 추적
21:30:15  Client → API Gateway          영상 URL 요청 수신
21:30:16  API Gateway → YouTube Extractor  오디오 추출 요청  
21:30:21  YouTube Extractor → STT Processor  오디오 파일 전달
21:30:26  STT Processor → AI Orchestrator   STT 결과 전송
```

**2) Kafka 메시지 흐름**
```
📨 Kafka 메시지 흐름
stt_requests        21:30:15  새로운 STT 요청: task-123
stt_results        21:30:45  STT 처리 완료: task-123
ai_processing_requests  21:30:46  AI 번역 요청: task-123  
ai_processing_results   21:31:15  AI 번역 완료: task-123
```

**3) 성능 분석 메트릭**
```
⚡ 처리 성능 분석
8초        45초        32초        85초
오디오 추출   음성 인식    AI 번역     총 처리 시간
```

---

## 🛠️ 실제 증거 수집을 위한 실행 순서

### **Step 1: 시스템 시작**
```bash
cd /Users/hongggggg/noCloudProgramming/졸업논문프로젝트/youtube-jp-translator/backend
docker-compose down -v
docker-compose build  
docker-compose up -d

# 프론트엔드 시작 (별도 터미널)
cd ../frontend
npm start
```

### **Step 2: 기본 상태 확인**
```bash
# 서비스 상태 스크린샷
docker-compose ps

# 헬스체크 로그
curl http://localhost:8080/health
curl http://localhost:8080/api/ai/agents/status
```

### **Step 3: 실제 번역 테스트 (증거 수집)**
1. **브라우저**: `http://localhost:3000` 접속
2. **YouTube URL 입력**: 5-10분 일본어 영상
3. **AI 모드 선택**: 표준 또는 프리미엄 모드
4. **증거 수집**:
   - AI 모드 선택 화면 스크린샷
   - 실시간 진행률 화면 스크린샷  
   - AI 에이전트 모니터링 화면 스크린샷
   - 시스템 모니터링 대시보드 스크린샷
   - 최종 병렬 번역 결과 스크린샷
   - 영상 동기화 하이라이트 동작 영상 녹화

### **Step 4: 로그 및 메트릭 수집**
```bash
# 실시간 로그 (별도 터미널들에서 실행)
docker-compose logs -f api-gateway
docker-compose logs -f stt-processor-api
docker-compose logs -f ai-orchestrator-api

# 시스템 메트릭 API 호출 (task_id는 실제 값으로 대체)
curl http://localhost:8080/api/system/metrics/[실제_task_id]
```

### **Step 5: 개발자 도구에서 추가 증거 수집**
- **Network 탭**: WebSocket 메시지 확인
- **Console 탭**: 디버깅 로그 확인  
- **Application 탭**: 로컬 스토리지 상태 확인

---

## 📋 논문 작성 시 활용 체크리스트

### **마이크로서비스 아키텍처 (3.1절)**
- [ ] `docker-compose ps` 실행 결과 스크린샷
- [ ] Docker Compose 파일의 서비스 정의 코드 발췌
- [ ] 각 서비스별 독립적 포트 및 환경 설정 증거

### **데이터 흐름 (3.2절)**  
- [ ] 시스템 모니터링 대시보드의 데이터 흐름 스크린샷
- [ ] Kafka 토픽별 메시지 흐름 로그
- [ ] WebSocket 실시간 통신 개발자 도구 스크린샷

### **사용자 경험 (3.3절)**
- [ ] 실시간 진행률 피드백 UI 스크린샷
- [ ] 원문-번역문 병렬 표시 UI 스크린샷  
- [ ] 영상 동기화 하이라이트 동작 동영상
- [ ] AI 에이전트 협업 과정 모니터링 스크린샷
- [ ] AI 모드 선택 인터페이스 스크린샷

### **성능 및 처리 시간**
- [ ] 처리 성능 분석 메트릭 스크린샷
- [ ] AI 에이전트별 처리 시간 타임라인
- [ ] 모드별 처리 시간 및 비용 비교표

---

## 🎯 주의사항

1. **실제 YouTube URL 사용**: 저작권 문제없는 교육/뉴스 콘텐츠 권장
2. **Gemini API 키 설정**: 실제 AI 처리를 위해 `backend/.env` 파일에 API 키 필요
3. **충분한 처리 시간**: 5-10분 영상 기준 1-2분 소요, 인내심 필요
4. **브라우저 호환성**: Chrome/Edge에서 최적 동작 확인
5. **네트워크 상태**: 안정적인 인터넷 연결 필수

---

**📞 문제 발생 시 디버깅**
```bash
# 서비스 상태 확인
docker-compose ps
docker-compose logs [서비스명]

# 포트 충돌 확인  
lsof -i :8080
lsof -i :3000

# 완전 재시작
docker-compose down -v
docker-compose build --no-cache
docker-compose up -d
```

이 가이드를 따라 실행하면 논문의 모든 설계 주장을 뒷받침하는 구체적이고 시각적인 증거들을 수집할 수 있습니다.