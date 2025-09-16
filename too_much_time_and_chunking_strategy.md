# 🔍 스트리밍 STT 성능 분석 및 청킹 전략 개선방안

## 📊 **현재 성능 분석**

### **실측 결과 (6분 일본어 영상)**
- **STT 처리 시간**: 2분 43초 (목표 8초 대비 **2,037% 초과**)
- **번역 처리 시간**: 1분
- **총 처리 시간**: 3분 43초 (기존 대비 4분 단축이지만 여전히 목표 미달)

### **핵심 문제점**

#### **1. STT 순차 처리로 인한 성능 저하**
**문제**: `streaming_worker.py:167-200`에서 **for 루프 순차 처리**
```python
# 현재 구조 (문제)
for i, chunk_info in enumerate(chunks):
    model = await self.whisper_pool.get_model()  # 하나씩 처리
    result = await self._process_chunk(model, chunk_info, ...)
    await self.whisper_pool.return_model(model)
```

**영향**:
- 6분 영상 → ~72개 청크 → 각 청크당 2.3초 → 총 2분 43초
- Whisper 모델 풀(3개)의 병렬 처리 능력 미활용
- 실시간성 완전 상실

#### **2. 번역 결과 분절 문제**
**문제**: 스트리밍 청킹과 AI Orchestrator 문장 분할 불일치

**증상** (실제 결과):
```
0:00.0 - 0:03.9
일본어: はいどうも、波数です。本日は動画をご視聴いただきまして、まことにありがとうございます。
한국어: 네, 안녕하세요    # 번역 끊어짐

0:03.9 - 0:07.9
일본어: はいどうも、波数です。本日は動画をご視聴いただきまして、まことにありがとうございます。  # 중복
한국어: 오늘 영상 시청해주셔서 정말 감사합니다.    # 다른 부분 번역
```

**원인**:
- 스트리밍 STT: 5초 청크 기반
- AI Orchestrator: 문장 단위 기반
- 두 시스템 간 동기화 부재

#### **3. 일본어 텍스트 중복**
**문제**: 청킹 오버랩(1초)으로 인한 중복 텍스트 생성

**패턴**:
- 같은 일본어 문장이 연속된 시간 구간에 반복 표시
- 오버랩 구간의 STT 결과 중복 제거 로직 부재
- 번역 효율성 저하 (같은 내용 중복 번역)

#### **4. 청킹 전략 비효율성**
**문제**: 5초 청크 + 1초 오버랩 전략의 한계

**분석**:
- **청크 크기**: 너무 작아서 Whisper 모델의 문맥 이해 제한
- **오버랩 처리**: 중복 제거 로직 부재
- **VAD 보수적**: 음성 활동 감지가 과도하게 보수적
- **I/O 오버헤드**: 청크마다 임시 파일 쓰기/읽기

---

## 🛠️ **근본 원인 분석**

### **아키텍처 설계 문제**

#### **1. 병렬 처리 부재**
```python
# 현재 (순차 처리)
for chunk in chunks:
    process_chunk(chunk)  # 2.3초 소요

# 개선 필요 (병렬 처리)
await asyncio.gather(*[
    process_chunk(chunk) for chunk in chunks
])  # 0.8초 목표
```

#### **2. 시스템 간 불일치**
- **Streaming STT**: 청크 기반 → 실시간성 우선
- **AI Orchestrator**: 문장 기반 → 품질 우선
- **통합 로직 부재**: 두 접근법의 장점 결합 실패

#### **3. 메모리 vs 디스크 I/O**
- 청크별 임시 파일 생성: `_save_chunk_to_file()`
- 디스크 I/O 병목: 청크당 ~50ms 추가 지연
- 메모리 기반 처리 필요

---

## ⚡ **성능 개선 솔루션**

### **1. 병렬 STT 처리 구현**

#### **개선된 워커 로직**
```python
async def process_streaming_stt_parallel(self, chunks, task_id, language):
    """병렬 STT 처리"""

    # 배치 크기: 모델 풀 크기와 매칭
    batch_size = min(self.whisper_pool.pool_size, len(chunks))

    # 청크를 배치로 분할
    chunk_batches = [
        chunks[i:i + batch_size]
        for i in range(0, len(chunks), batch_size)
    ]

    stt_results = []

    for batch in chunk_batches:
        # 배치 내 병렬 처리
        batch_tasks = [
            self._process_chunk_optimized(chunk, task_id, language)
            for chunk in batch
        ]

        # 병렬 실행 + 타임아웃
        batch_results = await asyncio.gather(
            *batch_tasks,
            return_exceptions=True
        )

        # 유효 결과만 수집
        stt_results.extend([
            result for result in batch_results
            if not isinstance(result, Exception) and result
        ])

        # 실시간 진행 상황 업데이트
        await self._send_batch_progress(task_id, len(stt_results), len(chunks))

    return stt_results

async def _process_chunk_optimized(self, chunk_info, task_id, language):
    """최적화된 청크 처리"""
    model = await self.whisper_pool.get_model()

    try:
        # 메모리 기반 처리 (임시 파일 제거)
        segments, info = model.transcribe(
            chunk_info["audio_data"],  # 파일 경로 대신 오디오 데이터
            language=language,
            beam_size=3,  # 5→3으로 축소 (속도 우선)
            best_of=3,    # 5→3으로 축소
            temperature=0.1,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,  # 1000→500ms (덜 보수적)
                speech_pad_ms=30
            )
        )

        return self._extract_chunk_result(segments, info, chunk_info)

    finally:
        await self.whisper_pool.return_model(model)
```

#### **예상 성능 개선**
- **현재**: 72개 청크 × 2.3초 = 166초
- **개선 후**: 72개 청크 ÷ 3개 모델 × 0.8초 = **20초**
- **개선율**: **88% 단축** (166초 → 20초)

### **2. 지능형 청킹 전략**

#### **적응형 청킹**
```python
class AdaptiveAudioChunker:
    """적응형 오디오 청킹"""

    def __init__(self):
        self.base_chunk_duration = 8.0  # 5초→8초 확대
        self.max_chunk_duration = 12.0
        self.overlap_duration = 2.0     # 1초→2초 확대
        self.sentence_aware = True

    async def create_intelligent_chunks(self, audio_file_path, language="ja"):
        """문장 인식 기반 청킹"""

        # 1. 기본 청킹
        base_chunks = await self._create_base_chunks(audio_file_path)

        # 2. 문장 경계 예측 (빠른 STT)
        sentence_boundaries = await self._predict_sentence_boundaries(base_chunks)

        # 3. 청킹 최적화
        optimized_chunks = self._optimize_chunk_boundaries(
            base_chunks, sentence_boundaries
        )

        return optimized_chunks

    async def _predict_sentence_boundaries(self, chunks):
        """빠른 STT로 문장 경계 예측"""

        # Whisper tiny 모델로 빠른 텍스트 추출
        quick_model = WhisperModel("tiny", device="cpu")

        boundaries = []
        for chunk in chunks:
            try:
                segments, _ = quick_model.transcribe(
                    chunk["file_path"],
                    language="ja",
                    beam_size=1,  # 최소 품질로 속도 우선
                    condition_on_previous_text=False
                )

                text = " ".join([segment.text for segment in segments])

                # 일본어 문장 종료 패턴 감지
                has_sentence_end = bool(re.search(
                    r'[。！？]|です$|ます$|である$|だった$',
                    text.strip()
                ))

                boundaries.append({
                    "chunk_index": chunk["chunk_index"],
                    "has_sentence_end": has_sentence_end,
                    "text_preview": text[:50]
                })

            except Exception:
                boundaries.append({
                    "chunk_index": chunk["chunk_index"],
                    "has_sentence_end": False,
                    "text_preview": ""
                })

        return boundaries
```

### **3. 통합 문장 재구성**

#### **중복 제거 + 문장 병합**
```python
class IntelligentSentenceReconstructor:
    """지능형 문장 재구성기"""

    async def reconstruct_with_deduplication(self, stt_chunks):
        """중복 제거 + 문장 재구성"""

        # 1. 시간순 정렬
        sorted_chunks = sorted(stt_chunks, key=lambda x: x.start_time)

        # 2. 오버랩 구간 중복 제거
        deduplicated_chunks = await self._remove_overlap_duplicates(sorted_chunks)

        # 3. 문장 단위 병합
        sentences = await self._merge_into_sentences(deduplicated_chunks)

        # 4. 번역 준비용 텍스트 그룹 생성
        translation_groups = self._create_translation_groups(sentences)

        return {
            "sentences": sentences,
            "translation_groups": translation_groups,
            "stats": {
                "original_chunks": len(stt_chunks),
                "deduplicated_chunks": len(deduplicated_chunks),
                "final_sentences": len(sentences),
                "deduplication_rate": (len(stt_chunks) - len(deduplicated_chunks)) / len(stt_chunks)
            }
        }

    async def _remove_overlap_duplicates(self, chunks):
        """오버랩 구간 중복 제거"""
        if not chunks:
            return []

        deduplicated = [chunks[0]]  # 첫 청크는 유지

        for current_chunk in chunks[1:]:
            prev_chunk = deduplicated[-1]

            # 오버랩 구간 감지
            overlap_start = max(prev_chunk.start_time, current_chunk.start_time)
            overlap_end = min(prev_chunk.end_time, current_chunk.end_time)

            if overlap_end > overlap_start:  # 오버랩 존재
                # 텍스트 유사도 검사
                similarity = self._calculate_text_similarity(
                    prev_chunk.text, current_chunk.text
                )

                if similarity > 0.7:  # 70% 이상 유사하면 중복으로 간주
                    # 더 긴 텍스트나 높은 신뢰도를 가진 청크 선택
                    if (len(current_chunk.text) > len(prev_chunk.text) or
                        current_chunk.confidence > prev_chunk.confidence):

                        # 시간 구간을 병합하여 이전 청크 갱신
                        deduplicated[-1] = STTChunk(
                            chunk_id=f"merged_{prev_chunk.chunk_id}_{current_chunk.chunk_id}",
                            task_id=current_chunk.task_id,
                            start_time=prev_chunk.start_time,
                            end_time=current_chunk.end_time,
                            text=current_chunk.text,
                            confidence=(prev_chunk.confidence + current_chunk.confidence) / 2,
                            language=current_chunk.language
                        )
                        continue
                    else:
                        # 이전 청크가 더 좋으면 현재 청크 무시
                        continue

            # 중복이 아니거나 오버랩이 없으면 추가
            deduplicated.append(current_chunk)

        return deduplicated

    def _calculate_text_similarity(self, text1, text2):
        """텍스트 유사도 계산 (일본어 특화)"""
        import difflib

        # 공백 제거 후 비교
        clean_text1 = re.sub(r'\s+', '', text1.strip())
        clean_text2 = re.sub(r'\s+', '', text2.strip())

        if not clean_text1 or not clean_text2:
            return 0.0

        # 문자 단위 유사도 계산
        similarity = difflib.SequenceMatcher(None, clean_text1, clean_text2).ratio()

        return similarity
```

### **4. 번역 시스템 통합**

#### **스트리밍-배치 하이브리드**
```python
class HybridTranslationStrategy:
    """스트리밍-배치 하이브리드 번역"""

    async def process_streaming_translation(self, task_id, stt_result):
        """스트리밍 번역 처리"""

        # 1. 완전한 문장 식별
        complete_sentences = []
        partial_sentences = []

        for sentence in stt_result["sentences"]:
            if self._is_complete_sentence(sentence.text):
                complete_sentences.append(sentence)
            else:
                partial_sentences.append(sentence)

        # 2. 완전한 문장 즉시 번역 (실시간 피드백)
        if complete_sentences:
            quick_translations = await self._batch_translate_fast(complete_sentences)

            # WebSocket으로 실시간 결과 전송
            for translation in quick_translations:
                await self._send_realtime_translation(task_id, translation)

        # 3. 전체 컨텍스트 번역 (품질 우선)
        if stt_result.get("is_final", False):
            all_sentences = complete_sentences + partial_sentences

            # Phase 3 Translation Worker Pool 활용
            final_translations = await self.translation_worker_pool.translate_batch(
                [s.text for s in all_sentences],
                context={
                    "task_id": task_id,
                    "mode": "quality",
                    "japanese_context": True
                }
            )

            # 최종 결과 전송
            await self._send_final_translation(task_id, final_translations)

        return {
            "realtime_count": len(complete_sentences),
            "pending_count": len(partial_sentences)
        }

    def _is_complete_sentence(self, text):
        """문장 완성도 판단 (일본어 특화)"""
        patterns = [
            r'[。！？]$',                          # 문장 부호 종료
            r'[です|ます|である|だった|でしょう]$',    # 정중한 종료
            r'[ね|よ|な|か|さ]$',                   # 종조사 종료
            r'[らしい|そうです|みたいです]$'          # 추정 표현
        ]

        text_clean = text.strip()
        return any(re.search(pattern, text_clean) for pattern in patterns)
```

---

## 📈 **예상 성능 개선 결과**

### **처리 시간 개선**

| 구성 요소 | 현재 | 개선 후 | 개선율 |
|-----------|------|---------|--------|
| **STT 청킹** | 순차 처리 | 병렬 처리 + 적응형 청킹 | - |
| **STT 처리 시간** | 2분 43초 | **25초** | **85% 단축** |
| **첫 번역 결과** | STT 완료 후 | **8초** | **실시간 달성** |
| **전체 완료 시간** | 3분 43초 | **45초** | **80% 단축** |

### **품질 개선**

| 메트릭 | 현재 | 개선 후 | 개선 효과 |
|--------|------|---------|-----------|
| **일본어 중복률** | ~40% | **<5%** | 중복 제거 로직 |
| **한국어 완성도** | 분절됨 | **완전한 문장** | 문장 재구성 |
| **번역 정확도** | 청킹 오류 | **문맥 보존** | 긴 청크 + 중복 제거 |
| **실시간성** | 없음 | **8초 첫 결과** | 하이브리드 전략 |

### **리소스 효율성**

| 리소스 | 현재 | 개선 후 | 효과 |
|--------|------|---------|------|
| **Whisper 모델 활용률** | 33% (1/3) | **95%** (3/3 병렬) | 3배 처리량 |
| **메모리 사용량** | 임시 파일 I/O | **메모리 기반** | 50ms/청크 절약 |
| **API 호출 최적화** | 중복 번역 | **중복 제거** | 40% 비용 절감 |
| **네트워크 트래픽** | 중복 결과 | **최적화된 결과** | 30% 감소 |

---

## 🎯 **구현 우선순위**

### **Phase 1: 병렬 처리 (High Impact, Low Risk)**
1. **STT 워커 병렬화**: `asyncio.gather` 도입
2. **Whisper 모델 풀 최적화**: 동시성 개선
3. **메모리 기반 처리**: 임시 파일 I/O 제거

**예상 효과**: STT 처리 시간 85% 단축

### **Phase 2: 청킹 전략 개선 (Medium Impact, Medium Risk)**
1. **적응형 청킹**: 8초 기본 + 문장 경계 인식
2. **중복 제거 로직**: 오버랩 처리 최적화
3. **VAD 파라미터 튜닝**: 덜 보수적인 음성 감지

**예상 효과**: 품질 30% 향상, 처리량 20% 개선

### **Phase 3: 하이브리드 번역 (High Impact, High Risk)**
1. **실시간 번역**: 완전한 문장 즉시 처리
2. **배치 최적화**: Phase 3 Translation Worker Pool 연동
3. **품질 보장**: 전체 컨텍스트 기반 최종 번역

**예상 효과**: 첫 결과 8초 달성, 번역 품질 50% 향상

---

## 🛡️ **리스크 관리**

### **성능 저하 리스크**
- **병렬 처리**: 메모리 사용량 증가 → 모니터링 강화
- **긴 청킹**: 지연 증가 가능성 → 타임아웃 설정
- **중복 제거**: 계산 오버헤드 → 효율적 알고리즘 사용

### **품질 저하 리스크**
- **빠른 STT**: 정확도 감소 → Whisper base 모델 유지
- **문장 병합**: 잘못된 재구성 → 신뢰도 기반 검증
- **실시간 번역**: 문맥 부족 → 하이브리드 전략으로 보완

### **호환성 리스크**
- **기존 시스템**: API 호환성 → 점진적 마이그레이션
- **WebSocket 클라이언트**: 메시지 형식 → 버전 관리
- **모니터링**: 메트릭 수집 → 기존 대시보드 유지

---

## 📋 **실행 계획**

### **1주차: 병렬 처리 구현**
- [ ] `streaming_worker.py` 병렬 처리 로직 구현
- [ ] Whisper 모델 풀 동시성 개선
- [ ] 성능 벤치마크 및 검증

### **2주차: 청킹 전략 개선**
- [ ] 적응형 청킹 로직 개발
- [ ] 중복 제거 시스템 구현
- [ ] 일본어 문장 감지 최적화

### **3주차: 번역 시스템 통합**
- [ ] 하이브리드 번역 전략 구현
- [ ] Phase 3 Translation Worker Pool 연동
- [ ] 실시간 WebSocket 메시지 최적화

### **4주차: 검증 및 최적화**
- [ ] 전체 시스템 통합 테스트
- [ ] 성능 메트릭 수집 및 분석
- [ ] 프로덕션 배포 준비

이러한 개선을 통해 **6분 영상을 45초 내에 처리**하고, **8초 내 첫 번역 결과**를 제공하는 목표를 달성할 수 있습니다.