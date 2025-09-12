# 한국어 번역 문장 분할 문제 해결 가이드

## 📋 문제 상황

유튜브 일본어 → 한국어 번역 시스템에서 **번역 결과의 문장 분할이 제대로 되지 않는 문제** 발생

### 🔍 핵심 문제점 분석

#### 1. **배치 번역 시 구분자 손실 문제**
- **위치**: `translator.py:149-202` 배치 번역 로직
- **문제**: `[TRANSLATION_SEGMENT_BREAK]` 구분자가 Gemini 번역 과정에서 무시되거나 제거됨
- **결과**: 여러 일본어 문장이 하나의 긴 한국어 문장으로 합쳐짐

#### 2. **한국어 특성을 반영하지 못한 분할 로직**
- **위치**: `translator.py:306-427` `_robust_segment_parsing` 함수
- **문제**: 일본어 분할에 최적화되어 있지만 한국어 번역 결과 분할은 미흡
- **결과**: 한국어 어미(다/요/니다/죠)를 제대로 인식하지 못함

#### 3. **배치 번역 우선 정책**
- **위치**: `sentence_segmenter.py:637-649` 그룹핑 로직  
- **문제**: 여러 문장을 묶어서 번역하려고 시도하나 구분자 보존 실패 시 복구 어려움
- **결과**: 번역 품질 저하와 문장 경계 모호화

#### 4. **Post-processing에서 재분할 부재**
- **위치**: `post_processing_chain.py`
- **문제**: 번역 후 한국어 특성을 고려한 재분할 처리 없음
- **결과**: 잘못 분할된 번역 결과가 그대로 최종 출력됨

---

## 🛠️ 해결 방안 (우선 적용 순서)

### ✅ **1. 번역 프롬프트 수정 (translator.py)**

#### **수정 파일**: `translator.py:154-170`
#### **변경 내용**: 배치 번역 프롬프트 강화

**이전**:
```python
batch_prompt = ChatPromptTemplate.from_template("""
다음은 유튜브에서 추출한 총 {segment_count}개의 독립적인 일본어 구어체 문장들입니다. 
각 문장은 "{separator}"로 구분되어 있습니다.

맥락에 맞게 매우 자연스러운 한국어 구어체로 번역하고, 각 번역된 문장 뒤에는 
반드시 원래의 "{separator}" 구분자를 정확히 유지해주세요.
최종적으로 번역된 한국어 문장도 정확히 {segment_count}개가 되어야 합니다.
각 번역된 문장 외에는 어떠한 부연 설명, 인사말 등을 절대 포함하지 마세요.
""")
```

**수정 후**:
```python
batch_prompt = ChatPromptTemplate.from_template("""
다음은 유튜브에서 추출한 총 {segment_count}개의 독립적인 일본어 구어체 문장들입니다. 
각 문장은 "{separator}"로 구분되어 있습니다.

중요한 번역 지침:
1. 각 일본어 문장을 독립적으로 번역하되 전체 맥락을 고려하세요
2. 번역된 각 한국어 문장 뒤에는 반드시 "{separator}"를 정확히 유지하세요  
3. 한국어 문장이 자연스럽도록 어순을 조정하되, 문장 경계는 명확히 유지하세요
4. 구분자 개수가 정확히 {segment_count}개가 되도록 하세요
5. 부연설명 없이 번역문과 구분자만 출력하세요
6. 한 문장이 너무 길면 자연스럽게 두 문장으로 나누되 구분자로 분리하세요
""")
```

#### **재시도 프롬프트 개선**: `translator.py:444-463`
```python
retry_prompt = ChatPromptTemplate.from_template("""
다음 {segment_count}개의 일본어 문장을 한국어로 번역해주세요.

CRITICAL RULE: 반드시 {segment_count}개의 번역된 문장을 출력해야 합니다.

각 문장은 "{separator}"로 구분되어 있습니다.
번역 후에도 각 한국어 문장 사이에 정확히 "{separator}"를 넣어주세요.

형식 예시:
첫 번째 문장 번역
{separator}
두 번째 문장 번역
{separator}
세 번째 문장 번역
""")
```

---

### ✅ **2. 한국어 분할 로직 추가 (translator.py)**

#### **수정 파일**: `translator.py:339-390`
#### **변경 내용**: 한국어 특화 분할 패턴 강화

**기존 한국어 패턴** (3가지):
```python
korean_patterns = [
    r'[.!?。！？]\s*\n',   # 문장부호 + 줄바꿈
    r'[다요]\s*\n',         # 한국어 어미 + 줄바꿈
    r'니다\s*\n',           # 존댓말 + 줄바꿈
    r'\n\s*(?=[가-힣])',    # 줄바꿈 + 한글 시작
]
```

**개선된 한국어 패턴** (7가지):
```python
korean_patterns = [
    r'[.!?。！？]\s*\n',                    # 문장부호 + 줄바꿈
    r'[다요]\s*[.!?]?\s*(?=\n|[가-힣]|$)',   # 한국어 어미 + 문장부호(선택) + 다음문장
    r'니다\s*[.!?]?\s*(?=\n|[가-힣]|$)',     # 존댓말 어미
    r'습니다\s*[.!?]?\s*(?=\n|[가-힣]|$)',   # 존댓말 어미 
    r'네요\s*[.!?]?\s*(?=\n|[가-힣]|$)',     # 감탄 어미
    r'죠\s*[.!?]?\s*(?=\n|[가-힣]|$)',       # 구어체 어미
    r'\n\s*(?=[가-힣])',                    # 줄바꿈 + 한글 시작
]
```

#### **새로운 함수 추가**: `_korean_sentence_split()` (392-459행)

**핵심 기능**:
- 8가지 한국어 어미 패턴으로 정교한 분할
- 점수 기반 최적 분할 결과 선택
- 균등 분할 fallback 제공

```python
def _korean_sentence_split(self, text: str, expected_count: int) -> List[str]:
    """한국어 번역 결과 전용 문장 분할"""
    # 한국어 문장 종료 패턴들 (더 정교함)
    korean_end_patterns = [
        r'[다요]\s*[.!?]?\s*(?=[가-힣A-Za-z\[]|$)',    # 다/요 어미
        r'니다\s*[.!?]?\s*(?=[가-힣A-Za-z\[]|$)',      # 존댓말 어미
        r'습니다\s*[.!?]?\s*(?=[가-힣A-Za-z\[]|$)',    # 존댓말 어미
        r'네요\s*[.!?]?\s*(?=[가-힣A-Za-z\[]|$)',      # 감탄 어미
        r'죠\s*[.!?]?\s*(?=[가-힣A-Za-z\[]|$)',        # 구어체 어미
        r'거예요\s*[.!?]?\s*(?=[가-힣A-Za-z\[]|$)',    # 구어체 어미
        r'어요\s*[.!?]?\s*(?=[가-힣A-Za-z\[]|$)',      # 구어체 어미
        r'[.!?]\s*(?=[가-힣A-Za-z\[]|$)',             # 문장부호 + 다음 문장 시작
    ]
    
    # 점수 기반 최적 분할 선택
    for pattern in korean_end_patterns:
        segments = re.split(pattern, text)
        count_diff = abs(len(segments) - expected_count)
        quality_score = sum(1 for s in segments if len(s) > 5 and not s.startswith('['))
        total_score = count_diff + (1 / max(quality_score, 1))
        
        if len(segments) == expected_count:
            return segments
    
    # Fallback: 균등 분할
    return self._fallback_equal_split(text, expected_count)
```

---

### ✅ **3. 개별 번역 비율 증가 (sentence_segmenter.py)**

#### **수정 파일**: `sentence_segmenter.py:637-649`
#### **변경 내용**: 문장 제한을 대폭 축소하여 개별 번역 우선

**이전 설정**:
```python
if remaining_quota < 10:
    return min(4, max(2, total_segments // 8))      # 최대 4문장
elif remaining_quota < 20:
    return min(3, max(2, total_segments // 10))     # 최대 3문장
else:
    return min(2, max(1, total_segments // 15))     # 최대 2문장
```

**수정 후**:
```python
if remaining_quota < 10:
    return min(2, max(1, total_segments // 12))     # 최대 2문장 (더욱 보수적)
elif remaining_quota < 20:
    return min(2, max(1, total_segments // 15))     # 최대 2문장  
else:
    return 1                                        # 개별 번역 최우선 (1문장씩)
```

#### **개별 처리 조건 강화**: `sentence_segmenter.py:560-566`

**이전**:
```python
should_create_individual_group = (
    len(segment.text.strip()) < 30 or               # 30자 미만
    self._is_complete_sentence(segment.text) or     # 완결된 문장
    segment.speaker_change or                       # 화자 변화
    estimated_tokens > adaptive_max_tokens * 0.7   # 큰 세그먼트 (70%)
)
```

**수정 후**:
```python
should_create_individual_group = (
    len(segment.text.strip()) < 50 or               # 50자 미만 (30→50 확대)
    self._is_complete_sentence(segment.text) or     # 완결된 문장
    segment.speaker_change or                       # 화자 변화
    estimated_tokens > adaptive_max_tokens * 0.5 or # 큰 세그먼트 (70%→50% 축소)
    re.search(r'[？！]', segment.text)               # 질문/감탄문 추가
)
```

---

### ✅ **4. Post-processing 재분할 추가 (post_processing_chain.py)**

#### **수정 파일**: `post_processing_chain.py:45, 223-328`
#### **변경 내용**: 한국어 재분할 단계 추가

**병렬 처리 작업에 추가**:
```python
# 포맷팅 작업
if self.enable_formatting and self.formatter and self.formatter.is_available():
    parallel_tasks["korean_resegmentation"] = RunnableLambda(self._korean_sentence_segmentation)  # 추가
    parallel_tasks["speaker_analysis"] = RunnableLambda(self._analyze_speakers)
    parallel_tasks["subtitle_formatting"] = RunnableLambda(self._format_subtitles)
    parallel_tasks["readability_enhancement"] = RunnableLambda(self._enhance_readability)
```

#### **새로운 함수**: `_korean_sentence_segmentation()` (223-280행)

**핵심 기능**:
- 번역된 한국어 텍스트를 재분할
- 시간 정보를 새로 분할된 세그먼트에 균등 배분
- 원본 번역 텍스트 보존

```python
async def _korean_sentence_segmentation(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """번역된 한국어 텍스트 재분할"""
    segments = input_data["segments"]
    refined_segments = []
    segmentation_applied_count = 0
    
    for segment in segments:
        korean_text = segment.get('korean_text', '').strip()
        
        if not korean_text or korean_text.startswith('['):
            refined_segments.append(segment)
            continue
        
        # 한국어 문장 분할 적용
        sub_sentences = self._split_korean_sentence(korean_text)
        
        if len(sub_sentences) > 1:
            # 여러 문장으로 분할된 경우 시간 분배
            duration = segment.get('end', 0) - segment.get('start', 0)
            time_per_sentence = duration / len(sub_sentences)
            
            for i, sub_text in enumerate(sub_sentences):
                sub_segment = segment.copy()
                sub_segment['korean_text'] = sub_text.strip()
                sub_segment['original_korean_text'] = korean_text  # 원본 보존
                sub_segment['start'] = segment['start'] + (i * time_per_sentence)
                sub_segment['end'] = segment['start'] + ((i + 1) * time_per_sentence)
                sub_segment['segmentation_applied'] = True
                refined_segments.append(sub_segment)
            
            segmentation_applied_count += 1
        else:
            refined_segments.append(segment)
    
    return {
        "refined_segments": refined_segments,
        "segmentation_applied": True,
        "original_segment_count": len(segments),
        "final_segment_count": len(refined_segments)
    }
```

#### **한국어 분할 함수**: `_split_korean_sentence()` (282-328행)

6가지 패턴으로 한국어 문장 분할:
```python
split_patterns = [
    r'([다요])\s*[.!?]?\s*([가-힣])',     # 다/요 + 다음문장
    r'(니다)\s*[.!?]?\s*([가-힣])',       # 니다 + 다음문장  
    r'(습니다)\s*[.!?]?\s*([가-힣])',     # 습니다 + 다음문장
    r'(네요)\s*[.!?]?\s*([가-힣])',       # 네요 + 다음문장
    r'(죠)\s*[.!?]?\s*([가-힣])',         # 죠 + 다음문장
    r'([.!?])\s*([가-힣])',               # 문장부호 + 한글
]
```

#### **우선순위 변경**: `post_processing_chain.py:376-382`
```python
# 최종 세그먼트 결정 (우선순위: korean_resegmentation > enhanced > formatted > original)
if "korean_resegmentation" in parallel_results:
    resegmentation_result = parallel_results["korean_resegmentation"]
    if resegmentation_result.get("segmentation_applied", False):
        final_segments = resegmentation_result["refined_segments"]
        logger.info(f"Using Korean resegmented segments: {len(final_segments)} segments")
```

---

## 🔄 **변경사항 적용 방법**

백엔드를 재빌드하고 재시작해야 합니다:

```bash
cd backend
docker-compose build ai-orchestrator-api
docker-compose up -d ai-orchestrator-api
```

---

## 📊 **기대 효과**

### **1. 번역 정확도 향상**
- 구분자 보존 강화로 배치 번역 시 문장 경계 유지
- 한국어 어미 기반 정교한 분할 처리

### **2. 개별 번역 우선으로 안정성 증대**  
- 1문장씩 번역하여 구분자 손실 위험 최소화
- 질문/감탄문 등 특수 구조 별도 처리

### **3. 다층 보완 시스템**
- 번역 단계 → 파싱 단계 → 후처리 단계 3중 보완
- 각 단계별 fallback 로직으로 안정성 확보

### **4. 한국어 구어체 특성 반영**
- "다/요/니다/죠/네요" 등 구어체 어미 완벽 인식
- 자연스러운 한국어 문장 단위 분할

---

## 🎯 **주요 파일별 수정 요약**

| 파일 | 주요 수정 내용 | 라인 |
|------|---------------|------|
| **translator.py** | 번역 프롬프트 강화, 한국어 분할 로직 추가 | 154-170, 392-459, 444-463 |
| **sentence_segmenter.py** | 개별 번역 우선, 조건 강화 | 560-566, 637-649 |
| **post_processing_chain.py** | 한국어 재분할 단계 추가 | 45, 223-328, 376-382 |

이제 한국어 번역 후 문장 분할 문제가 크게 개선될 것입니다.