# 스트리밍 STT 워커 설계

## 핵심 개념
```python
class StreamingSTTWorker:
    def __init__(self):
        self.chunk_size = 5  # 5초 청크
        self.overlap_size = 1  # 1초 오버랩
        self.sentence_buffer = IntelligentSentenceBuffer()
        self.whisper_pool = WhisperModelPool(pool_size=3)

    async def process_audio_stream(self, audio_stream, task_id):
        """실시간 오디오 스트림 처리"""
        async for chunk in self.split_audio_chunks(audio_stream):
            # 병렬 STT 처리
            stt_result = await self.whisper_pool.transcribe_async(chunk)

            # 지능형 버퍼에 추가
            complete_sentences = await self.sentence_buffer.add_segment(
                stt_result, chunk.timestamp
            )

            # 완성된 문장이 있으면 즉시 번역 큐로 전송
            if complete_sentences:
                await self.send_to_translation_queue(complete_sentences, task_id)
```

## 핵심 최적화 포인트

### 1. 오디오 청크 최적화
- **현재**: 30초 단위 → **변경**: 5초 단위 (6배 빠른 반응)
- **오버랩**: 1초씩 중첩하여 문장 경계 누락 방지
- **병렬 처리**: 3개 워커가 동시에 다른 청크 처리

### 2. Whisper 모델 풀링
```python
class WhisperModelPool:
    def __init__(self, pool_size=3):
        self.models = [WhisperModel("base") for _ in range(pool_size)]
        self.queue = asyncio.Queue()

    async def transcribe_async(self, chunk):
        model = await self.queue.get()
        try:
            result = await asyncio.to_thread(model.transcribe, chunk)
            return result
        finally:
            await self.queue.put(model)
```

### 3. 지능형 문장 버퍼
```python
class IntelligentSentenceBuffer:
    def __init__(self):
        self.window_size = 15  # 15초 윈도우
        self.segments = []
        self.context_memory = {}

    async def add_segment(self, segment, timestamp):
        """세그먼트 추가 및 완성된 문장 반환"""
        self.segments.append(segment)

        # 문장 완성 감지 (일본어 특화)
        complete_sentences = self.detect_complete_sentences()

        # 시간 임계값 체크 (5초 이상 지연 시 강제 출력)
        if self.should_force_output(timestamp):
            complete_sentences.extend(self.force_output_pending())

        return complete_sentences

    def detect_complete_sentences(self):
        """일본어 문장 완성 감지"""
        patterns = [
            r'[。！？]',  # 문장 부호
            r'です[。\s]', r'ます[。\s]',  # 존댓말 어미
            r'だ[。\s]', r'である[。\s]'   # 평상말 어미
        ]
        # 패턴 매칭 로직...
```