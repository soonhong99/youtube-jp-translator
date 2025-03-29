# 서비스 간 통신 프로토콜

## 동기 통신 (REST API)
- API 게이트웨이 ↔ 클라이언트: GraphQL over HTTP
- API 게이트웨이 ↔ 번역 모델 서비스: REST API (Seldon Core)
- 내부 서비스 간 직접 통신: REST API (필요한 경우에만)

## 비동기 통신 (Kafka)
1. 유튜브 URL 제출
   - 토픽: `youtube-urls`
   - 생산자: API 게이트웨이
   - 소비자: 유튜브 추출 서비스
   - 메시지 형식: `{ "request_id": "uuid", "youtube_url": "url", "user_id": "id" }`

2. 오디오 추출 완료
   - 토픽: `audio-extracted`
   - 생산자: 유튜브 추출 서비스
   - 소비자: STT 서비스
   - 메시지 형식: `{ "request_id": "uuid", "audio_path": "path", "metadata": {...} }`

3. STT 변환 완료
   - 토픽: `text-transcribed`
   - 생산자: STT 서비스
   - 소비자: API 게이트웨이
   - 메시지 형식: `{ "request_id": "uuid", "segments": [{...}], "language": "ja" }`

4. 처리 상태 업데이트
   - 토픽: `processing-status`
   - 생산자: 모든 서비스
   - 소비자: API 게이트웨이
   - 메시지 형식: `{ "request_id": "uuid", "service": "name", "status": "status", "progress": 0.75 }`