"""
번역 에이전트 - LangChain 기반 일본어->한국어 번역
"""
import logging
import asyncio
import re
from typing import List, Dict, Any, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
import time
from datetime import datetime

from ..config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TEMPERATURE, TRANSLATION_FORCE_ONE_TO_ONE
from ..utils.api_tracker import get_api_tracker
from ..utils.circuit_breaker import get_circuit_breaker, CircuitBreakerConfig, CircuitBreakerOpenException

logger = logging.getLogger(__name__)

class TranslatorAgent:
    """LangChain 기반 번역 에이전트"""
    
    def __init__(self, model_name: str = None, temperature: float = None):
        self.model_name = model_name or GEMINI_MODEL
        self.temperature = temperature or GEMINI_TEMPERATURE
        self.llm = None
        self.chain = None
        self.api_tracker = get_api_tracker()
        self.current_task_id = "unknown"
        self.force_one_to_one = TRANSLATION_FORCE_ONE_TO_ONE
        
        # Circuit Breaker 초기화 (번역 전용)
        self.circuit_breaker = get_circuit_breaker("translation", CircuitBreakerConfig(
            quota_limit=200,     # 유료 API용 증가
            cost_limit=10.0,     # 일일 $10 제한
            failure_threshold=3, # 3회 연속 실패 시 차단
            recovery_timeout=300 # 5분 후 복구 시도
        ))
        
        self._initialize_chain()
    
    def set_task_id(self, task_id: str):
        """현재 작업 ID 설정"""
        self.current_task_id = task_id
    
    def _initialize_chain(self) -> bool:
        """번역 체인 초기화"""
        if not GEMINI_API_KEY:
            logger.warning("Gemini API key not found. Translator agent will be disabled.")
            return False
        
        try:
            # LangChain Gemini 모델 초기화
            self.llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                temperature=self.temperature,
                google_api_key=GEMINI_API_KEY
            )
            
            # 번역 프롬프트 템플릿
            translation_prompt = ChatPromptTemplate.from_template("""
            당신은 전문 일본어-한국어 번역가입니다. 유튜브 동영상에서 추출한 일본어 음성을 자연스러운 한국어로 번역해주세요.

            번역 지침:
            1. 구어체와 감정을 그대로 살려서 번역하세요
            2. 원문의 뉘앙스와 톤을 유지하세요
            3. 한국어 어순에 맞게 자연스럽게 번역하세요
            4. 일본어 특유의 존댓말과 경어는 한국어 존댓말로 적절히 변환하세요
            5. 번역 결과만 출력하고 부가 설명은 하지 마세요

            일본어 원문:
            {japanese_text}

            한국어 번역:
            """)
            
            # 번역 체인 구성
            self.chain = (
                translation_prompt
                | self.llm
                | StrOutputParser()
            )
            
            logger.info(f"Translation agent initialized with model: {self.model_name}, temperature: {self.temperature}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize translation chain: {e}")
            return False
    
    def is_available(self) -> bool:
        """에이전트 사용 가능 여부"""
        return self.chain is not None
    
    async def translate_single(self, japanese_text: str) -> str:
        """단일 텍스트 번역"""
        if not self.is_available():
            return "[번역 불가 - 에이전트 미초기화]"
        
        if not japanese_text.strip():
            return ""
        
        try:
            # API 호출 추적
            tracker = get_api_tracker()
            
            # Circuit Breaker로 보호된 번역 호출
            estimated_cost = self.api_tracker.estimate_tokens(japanese_text) * 0.000075  # Flash 모델 기준
            
            @tracker.track_api_call(self.current_task_id, "TranslatorAgent", "translate_single")
            async def _tracked_translation(text):
                return await self.chain.ainvoke({"japanese_text": text})
            
            # Circuit Breaker를 통한 호출
            result = await self.circuit_breaker.call(
                _tracked_translation, 
                japanese_text, 
                estimated_cost=estimated_cost
            )
            
            logger.debug(f"Single translation: '{japanese_text}' -> '{result}'")
            return result.strip()
            
        except CircuitBreakerOpenException as e:
            logger.warning(f"Translation blocked by circuit breaker: {e}")
            return "[번역 할당량 초과]"
        except Exception as e:
            logger.error(f"Translation error for '{japanese_text}': {e}")
            return "[번역 오류]"
    
    async def translate_batch(self, japanese_texts: List[str], cancel_event = None) -> List[str]:
        """번역 배치 처리 - 1:1 번역 우선, 필요시 배치 fallback"""
        # 취소 확인
        if cancel_event and cancel_event.is_set():
            logger.info(f"Translation cancelled before starting")
            return ["[번역 취소]"] * len(japanese_texts)
            
        if not self.is_available():
            return ["[번역 불가 - 에이전트 미초기화]"] * len(japanese_texts)
        
        if not japanese_texts:
            return []
        
        # 운영 강제 옵션: 무조건 1:1 경로 사용 (세그먼트 매칭 문제 방지)
        if self.force_one_to_one:
            logger.info("Force one-to-one translation enabled for segment matching reliability.")
            return await self._translate_one_to_one_guaranteed(japanese_texts, cancel_event)

        # 지능형 번역 전략 선택
        translation_strategy = await self._select_translation_strategy(japanese_texts)
        logger.info(f"Selected translation strategy: {translation_strategy} for {len(japanese_texts)} segments")
        
        if translation_strategy == "intelligent_grouping":
            return await self._translate_with_intelligent_grouping(japanese_texts, cancel_event)
        else:
            return await self._translate_one_to_one(japanese_texts, cancel_event)
    
    async def _translate_one_to_one(self, japanese_texts: List[str], cancel_event = None) -> List[str]:
        """1:1 번역 (순서 보장된 병렬 처리)"""
        if not japanese_texts:
            return []
        
        # 동적 병렬 처리 설정 (할당량 기반)
        max_concurrent = await self._calculate_optimal_concurrency(len(japanese_texts))
        semaphore = asyncio.Semaphore(max_concurrent)
        
        logger.info(f"Starting parallel 1:1 translation for {len(japanese_texts)} segments (max_concurrent: {max_concurrent})")
        
        try:
            # 순서 보장을 위한 병렬 번역 작업 생성
            tasks = []
            for i, text in enumerate(japanese_texts):
                task = self._translate_single_with_index(
                    text, i, semaphore, cancel_event
                )
                tasks.append(task)
            
            # 모든 태스크를 병렬 실행하되 인덱스 순서로 정렬
            indexed_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 인덱스 순서대로 정렬하여 원래 순서 보장
            sorted_results = sorted(
                [r for r in indexed_results if not isinstance(r, Exception)],
                key=lambda x: x[0] if isinstance(x, tuple) else 0
            )
            results = [r[1] if isinstance(r, tuple) else str(r) for r in sorted_results]
            
            # 예외 처리된 결과들을 원래 위치에 배치
            final_results = ["[순서 오류]"] * len(japanese_texts)
            exception_count = 0
            
            for indexed_result in indexed_results:
                if isinstance(indexed_result, Exception):
                    logger.warning(f"Translation task failed with exception: {indexed_result}")
                    exception_count += 1
                elif isinstance(indexed_result, tuple) and len(indexed_result) == 2:
                    index, result = indexed_result
                    if 0 <= index < len(final_results):
                        final_results[index] = result
                        
            
            # 결과 통계 계산
            success_count = 0
            failed_indices = []
            
            for i, result in enumerate(results):
                if result and not result.startswith('['):
                    success_count += 1
                else:
                    failed_indices.append(i)
            
            logger.info(f"Ordered 1:1 Translation completed: {success_count}/{len(japanese_texts)} successful, {len(failed_indices)} failed")
            
            # 실패한 항목들에 대해 순차 재시도 (3개 이하일 때만)
            if failed_indices and len(failed_indices) <= 3:
                logger.info(f"Retrying {len(failed_indices)} failed translations sequentially")
                await self._retry_failed_translations(results, japanese_texts, failed_indices, cancel_event)
            
            return results
            
        except Exception as e:
            logger.error(f"1:1 Translation error: {e}")
            # Fallback: 강제 옵션이면 개별(순차) 번역으로만 재시도, 아니면 배치 번역
            if self.force_one_to_one:
                logger.info("Force one-to-one is ON: falling back to individual translations (sequential/limited)")
                return await self._translate_individually(japanese_texts, cancel_event)
            else:
                logger.info("Falling back to batch translation")
                return await self._translate_batch_fallback(japanese_texts, cancel_event)
    
    async def _translate_single_with_semaphore(self, text: str, index: int, 
                                             semaphore: asyncio.Semaphore, cancel_event = None) -> str:
        """세마포어를 사용한 제한적 병렬 번역"""
        async with semaphore:
            # 취소 확인
            if cancel_event and cancel_event.is_set():
                return "[번역 취소]"
            
            # 빈 텍스트 처리
            if not text.strip():
                return ""
            
            try:
                # 개별 번역 실행
                translated = await self.translate_single(text.strip())
                
                # 성공/실패 로깅 (디버깅용 - 짧게)
                if not translated.startswith('['):
                    logger.debug(f"Translation {index} successful: {text[:20]}... -> {translated[:20]}...")
                else:
                    logger.debug(f"Translation {index} failed: {text[:20]}... -> {translated}")
                
                return translated
                
            except Exception as e:
                logger.warning(f"Translation {index} error: {e}")
                return f"[번역 실패] {text[:30]}..."
    
    async def _translate_single_with_index(self, text: str, index: int, 
                                         semaphore: asyncio.Semaphore, cancel_event = None) -> tuple:
        """인덱스 정보를 포함한 세마포어 제한적 병렬 번역"""
        async with semaphore:
            # 취소 확인
            if cancel_event and cancel_event.is_set():
                return (index, "[번역 취소]")
            
            # 빈 텍스트 처리
            if not text.strip():
                return (index, "")
            
            try:
                # 개별 번역 실행
                translated = await self.translate_single(text.strip())
                
                # 성공/실패 로깅 (디버깅용 - 짧게)
                if not translated.startswith('['):
                    logger.debug(f"Translation {index} successful: {text[:20]}... -> {translated[:20]}...")
                else:
                    logger.debug(f"Translation {index} failed: {text[:20]}... -> {translated}")
                
                return (index, translated)
                
            except Exception as e:
                logger.warning(f"Translation {index} error: {e}")
                return (index, f"[번역 실패] {text[:30]}...")
    
    async def _translate_one_to_one_guaranteed(self, japanese_texts: List[str], cancel_event = None) -> List[str]:
        """세그먼트 매칭 보장된 1:1 번역 (절대 순서 보장)"""
        if not japanese_texts:
            return []
        
        logger.info(f"Starting guaranteed 1:1 translation for {len(japanese_texts)} segments")
        results = []
        
        try:
            # 순차적으로 하나씩 번역 (순서 절대 보장)
            for i, text in enumerate(japanese_texts):
                # 취소 확인
                if cancel_event and cancel_event.is_set():
                    logger.info(f"Guaranteed translation cancelled at segment {i}/{len(japanese_texts)}")
                    # 나머지는 취소 마크로 채움
                    results.extend(["[번역 취소]"] * (len(japanese_texts) - i))
                    break
                
                if not text.strip():
                    results.append("")
                    continue
                
                try:
                    translated = await self.translate_single(text.strip())
                    results.append(translated)
                    logger.debug(f"Guaranteed translation {i+1}/{len(japanese_texts)}: '{text[:30]}...' -> '{translated[:30]}...'")
                    
                except Exception as e:
                    logger.warning(f"Guaranteed translation failed for segment {i}: {e}")
                    results.append(f"[번역 실패] {text[:50]}...")
            
            success_count = sum(1 for r in results if r and not r.startswith('['))
            logger.info(f"Guaranteed 1:1 Translation completed: {success_count}/{len(results)} successful")
            
            # 결과 개수가 입력과 정확히 일치하는지 확인
            if len(results) != len(japanese_texts):
                logger.error(f"CRITICAL: Result count mismatch! Expected {len(japanese_texts)}, got {len(results)}")
                # 길이 맞추기
                while len(results) < len(japanese_texts):
                    results.append("[매칭 오류]")
                results = results[:len(japanese_texts)]
            
            return results
            
        except Exception as e:
            logger.error(f"Guaranteed 1:1 Translation error: {e}")
            # 최종 안전장치: 원본 개수만큼 오류 메시지 반환
            return [f"[번역 시스템 오류] {text[:30]}..." for text in japanese_texts]
    
    async def _calculate_optimal_concurrency(self, text_count: int) -> int:
        """할당량 기반 최적 동시성 계산"""
        try:
            from ..utils.circuit_breaker import get_circuit_breaker
            
            breaker = get_circuit_breaker("translation")
            status = breaker.get_status()
            remaining_quota = status.get("remaining_quota", 50)
            
            # 할당량 기반 동시성 조절
            if remaining_quota >= 100:
                # 할당량 충분: 최대 병렬 처리
                optimal_concurrent = min(15, text_count)
                logger.info(f"High quota ({remaining_quota}): using max concurrency ({optimal_concurrent})")
            elif remaining_quota >= 50:
                # 할당량 보통: 중간 병렬 처리  
                optimal_concurrent = min(10, text_count)
                logger.info(f"Medium quota ({remaining_quota}): using medium concurrency ({optimal_concurrent})")
            elif remaining_quota >= 20:
                # 할당량 낮음: 제한적 병렬 처리
                optimal_concurrent = min(5, text_count)
                logger.info(f"Low quota ({remaining_quota}): using limited concurrency ({optimal_concurrent})")
            else:
                # 할당량 매우 낮음: 순차 처리
                optimal_concurrent = min(3, text_count)
                logger.info(f"Very low quota ({remaining_quota}): using minimal concurrency ({optimal_concurrent})")
            
            return optimal_concurrent
            
        except Exception as e:
            logger.warning(f"Failed to calculate optimal concurrency: {e}, using default")
            return min(8, text_count)  # 안전한 기본값
    
    async def _select_translation_strategy(self, japanese_texts: List[str]) -> str:
        """지능형 번역 전략 선택"""
        try:
            from ..utils.circuit_breaker import get_circuit_breaker
            
            breaker = get_circuit_breaker("translation")
            status = breaker.get_status()
            remaining_quota = status.get("remaining_quota", 50)
            
            # 기본적으로 1:1 번역 우선
            if len(japanese_texts) <= 2:
                return "one_to_one"  # 2개 이하는 항상 1:1
            
            # 할당량이 충분하고 특정 조건을 만족할 때만 지능형 그룹핑
            if remaining_quota >= 100 and len(japanese_texts) >= 10:
                # 그룹핑 가능한 세그먼트 비율 계산
                groupable_count = self._count_groupable_segments(japanese_texts)
                groupable_ratio = groupable_count / len(japanese_texts)
                
                # 70% 이상이 그룹핑 가능하면 지능형 그룹핑 사용
                if groupable_ratio >= 0.7:
                    logger.info(f"Intelligent grouping selected: {groupable_count}/{len(japanese_texts)} segments are groupable")
                    return "intelligent_grouping"
            
            logger.info("One-to-one translation selected (default safe strategy)")
            return "one_to_one"
            
        except Exception as e:
            logger.warning(f"Failed to select translation strategy: {e}, using one-to-one")
            return "one_to_one"
    
    def _count_groupable_segments(self, japanese_texts: List[str]) -> int:
        """그룹핑 가능한 세그먼트 수 계산"""
        groupable_count = 0
        
        for text in japanese_texts:
            text = text.strip()
            if not text:
                continue
                
            # 그룹핑 가능 조건 (매우 보수적)
            is_groupable = (
                len(text) <= 40 and  # 40자 이하의 짧은 문장
                not re.search(r'[？！]', text) and  # 질문이나 감탄 없음
                not re.search(r'[。]$', text) and  # 완결 문장부호로 끝나지 않음
                len([c for c in text if ord(c) > 0x3040]) >= 5  # 최소 5개 이상의 일본어 문자
            )
            
            if is_groupable:
                groupable_count += 1
        
        return groupable_count
    
    async def _translate_with_intelligent_grouping(self, japanese_texts: List[str], cancel_event = None) -> List[str]:
        """지능형 선택적 그룹핑 번역"""
        if not japanese_texts:
            return []
        
        logger.info(f"Starting intelligent grouping translation for {len(japanese_texts)} segments")
        
        try:
            # 지능형 그룹 생성
            groups = self._create_intelligent_groups(japanese_texts)
            logger.info(f"Created {len(groups)} intelligent groups from {len(japanese_texts)} segments")
            
            # 각 그룹을 처리
            all_results = []
            group_success_count = 0
            
            for group_idx, group_texts in enumerate(groups):
                if cancel_event and cancel_event.is_set():
                    logger.info(f"Intelligent grouping cancelled at group {group_idx}")
                    remaining = sum(len(g) for g in groups[group_idx:])
                    all_results.extend(["[번역 취소]"] * remaining)
                    break
                
                try:
                    if len(group_texts) == 1:
                        # 단일 세그먼트는 개별 처리
                        result = await self.translate_single(group_texts[0])
                        all_results.append(result)
                        if not result.startswith('['):
                            group_success_count += 1
                    else:
                        # 소규모 그룹은 제한적 배치 처리 (최대 2개)
                        group_results = await self._translate_small_group(group_texts, cancel_event)
                        all_results.extend(group_results)
                        group_success_count += sum(1 for r in group_results if not r.startswith('['))
                        
                except Exception as e:
                    logger.warning(f"Group {group_idx} translation failed: {e}")
                    fallback_results = [f"[그룹 번역 실패] {text[:20]}..." for text in group_texts]
                    all_results.extend(fallback_results)
            
            logger.info(f"Intelligent grouping completed: {group_success_count}/{len(japanese_texts)} successful")
            return all_results
            
        except Exception as e:
            logger.error(f"Intelligent grouping error: {e}, falling back to 1:1")
            return await self._translate_one_to_one(japanese_texts, cancel_event)
    
    def _create_intelligent_groups(self, japanese_texts: List[str], max_group_size: int = 2) -> List[List[str]]:
        """지능형 그룹 생성 (매우 보수적)"""
        groups = []
        current_group = []
        
        for text in japanese_texts:
            text = text.strip()
            if not text:
                if current_group:
                    groups.append(current_group)
                    current_group = []
                groups.append([""])  # 빈 텍스트는 단독 처리
                continue
            
            # 그룹핑 가능 여부 판단 (매우 엄격한 조건)
            can_group = (
                len(current_group) < max_group_size and
                len(text) <= 30 and  # 매우 짧은 문장만
                not re.search(r'[？！。]', text) and  # 문장 종결 기호 없음
                not text.endswith('です') and  # 정중체 어미로 끝나지 않음
                not text.endswith('ます') and
                len(current_group) == 0  # 첫 번째 세그먼트일 때만
            )
            
            if can_group:
                current_group.append(text)
            else:
                if current_group:
                    groups.append(current_group)
                current_group = [text]
        
        if current_group:
            groups.append(current_group)
        
        return groups
    
    async def _translate_small_group(self, group_texts: List[str], cancel_event = None) -> List[str]:
        """소규모 그룹 번역 (2개 이하)"""
        if len(group_texts) > 2:
            # 안전장치: 2개 초과시 개별 처리
            results = []
            for text in group_texts:
                result = await self.translate_single(text)
                results.append(result)
            return results
        
        # 간단한 결합 번역
        try:
            separator = " | "
            combined_text = separator.join(group_texts)
            
            # 소그룹용 간단한 프롬프트
            small_group_prompt = ChatPromptTemplate.from_template("""
            다음 {count}개의 짧은 일본어 문장을 한국어로 번역해주세요.
            각 문장은 " | "로 구분되어 있습니다.
            
            번역 후에도 각 문장을 " | "로 구분해서 {count}개의 번역문을 출력해주세요.
            
            일본어: {japanese_text}
            한국어: """)
            
            chain = small_group_prompt | self.llm | StrOutputParser()
            
            result = await chain.ainvoke({
                "japanese_text": combined_text,
                "count": len(group_texts)
            })
            
            # 결과 분할
            translated_parts = result.strip().split(" | ")
            if len(translated_parts) == len(group_texts):
                return [part.strip() for part in translated_parts]
            else:
                # 분할 실패시 개별 처리로 fallback
                logger.warning(f"Small group parsing failed, falling back to individual")
                results = []
                for text in group_texts:
                    individual_result = await self.translate_single(text)
                    results.append(individual_result)
                return results
                
        except Exception as e:
            logger.warning(f"Small group translation failed: {e}, using individual")
            results = []
            for text in group_texts:
                try:
                    result = await self.translate_single(text)
                    results.append(result)
                except Exception:
                    results.append(f"[번역 실패] {text[:20]}...")
            return results
    
    async def _retry_failed_translations(self, results: List[str], original_texts: List[str], 
                                        failed_indices: List[int], cancel_event = None):
        """실패한 번역들 재시도"""
        for idx in failed_indices:
            if cancel_event and cancel_event.is_set():
                break
                
            try:
                original_text = original_texts[idx]
                retry_translated = await self.translate_single(original_text.strip())
                if not retry_translated.startswith('['):
                    results[idx] = retry_translated
                    logger.info(f"Retry successful for segment {idx}")
                else:
                    logger.warning(f"Retry failed for segment {idx}")
            except Exception as e:
                logger.warning(f"Retry error for segment {idx}: {e}")
    
    async def _translate_batch_fallback(self, japanese_texts: List[str], cancel_event = None) -> List[str]:
        """기존 배치 번역 방식 (Fallback용)"""
        # 빈 텍스트 필터링
        filtered_texts = [text.strip() for text in japanese_texts if text.strip()]
        if not filtered_texts:
            return [""] * len(japanese_texts)
        
        try:
            # 구분자를 사용한 배치 번역
            separator = "[TRANSLATION_SEGMENT_BREAK]"
            combined_text = f"\n{separator}\n".join(filtered_texts)
            
            # 개선된 배치 번역용 프롬프트 (문장 경계 보존 강화)
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

            일본어 원문:
            {japanese_text}

            한국어 번역:
            """)
            
            batch_chain = (
                batch_prompt
                | self.llm
                | StrOutputParser()
            )
            
            # 마지막 취소 확인 - API 호출 전
            if cancel_event and cancel_event.is_set():
                logger.info(f"Translation cancelled before API call")
                return ["[번역 취소]"] * len(japanese_texts)
            
            # API 호출 추적 및 Circuit Breaker 보호
            tracker = get_api_tracker()
            estimated_cost = sum(self.api_tracker.estimate_tokens(text) for text in filtered_texts) * 0.000075
            
            @tracker.track_api_call(self.current_task_id, "TranslatorAgent", "translate_batch")
            async def _tracked_batch_translation():
                # API 호출 직전 취소 확인
                if cancel_event and cancel_event.is_set():
                    raise Exception(f"Translation cancelled during API call")
                return await batch_chain.ainvoke({
                    "japanese_text": combined_text,
                    "separator": separator,
                    "segment_count": len(filtered_texts)
                })
            
            # Circuit Breaker를 통한 배치 번역 호출
            result = await self.circuit_breaker.call(
                _tracked_batch_translation,
                estimated_cost=estimated_cost
            )
            
            # 결과 분할 - 개선된 파싱 로직
            translated_segments = self._robust_segment_parsing(result.strip(), separator, len(filtered_texts))
            
            # 세그먼트 수 검증 및 재시도 로직
            if len(translated_segments) == len(filtered_texts):
                logger.info(f"Batch translation successful: {len(filtered_texts)} segments using {self.model_name}")
                
                # 원본 배열과 매칭 (빈 텍스트 고려)
                result_list = []
                filtered_idx = 0
                for original_text in japanese_texts:
                    if original_text.strip():
                        result_list.append(translated_segments[filtered_idx].strip())
                        filtered_idx += 1
                    else:
                        result_list.append("")
                
                return result_list
            else:
                logger.warning(f"Batch translation segment mismatch: expected {len(filtered_texts)}, got {len(translated_segments)}")
                # 샘플 프리뷰 로깅 (안전 길이)
                preview = result.strip().replace('\n', ' ')[:180]
                logger.warning(f"Batch raw preview: {preview}...")
                
                # 1차 재시도: 더 엄격한 파싱으로 재시도
                retry_segments = self._alternative_segment_parsing(result.strip(), len(filtered_texts))
                if len(retry_segments) == len(filtered_texts):
                    logger.info(f"Batch translation recovered with alternative parsing")
                    result_list = []
                    filtered_idx = 0
                    for original_text in japanese_texts:
                        if original_text.strip():
                            result_list.append(retry_segments[filtered_idx].strip())
                            filtered_idx += 1
                        else:
                            result_list.append("")
                    return result_list
                
                # 2차 재시도: API 재호출 (1회만)
                logger.info("Attempting batch translation retry with improved prompt")
                retry_result = await self._retry_batch_translation(japanese_texts, cancel_event)
                if retry_result and len(retry_result) == len(japanese_texts):
                    return retry_result
                
                # 최종: 제한적 개별 번역 (최대 10개만)
                logger.warning("Batch fallback translation failed, using limited individual translation")
                return await self._limited_individual_translation(japanese_texts, max_individual=10)
                
        except CircuitBreakerOpenException as e:
            logger.warning(f"Batch fallback translation blocked by circuit breaker: {e}")
            return ["[번역 할당량 초과]"] * len(japanese_texts)
        except Exception as e:
            # 취소에 의한 예외인지 확인
            if "cancelled" in str(e).lower():
                logger.info(f"Batch fallback translation cancelled: {e}")
                return ["[번역 취소]"] * len(japanese_texts)
                
            logger.error(f"Batch fallback translation error: {e}")
            # 최종 Fallback: 제한적 개별 번역
            return await self._limited_individual_translation(japanese_texts, max_individual=5)
    
    async def _translate_individually(self, japanese_texts: List[str], cancel_event = None) -> List[str]:
        """개별 번역 (배치 실패 시 fallback) - 제한적 처리"""
        logger.info(f"Falling back to individual translation for {len(japanese_texts)} segments")
        
        # Circuit Breaker 상태 확인하여 과도한 API 호출 방지
        try:
            breaker_status = self.circuit_breaker.get_status()
            remaining_quota = breaker_status.get("remaining_quota", 0)
            
            # 할당량이 부족하면 제한적으로만 번역
            max_individual_translations = min(len(japanese_texts), remaining_quota // 2, 20)  # 최대 20개까지만
            
            if max_individual_translations < len(japanese_texts):
                logger.warning(f"Limited individual translation: {max_individual_translations}/{len(japanese_texts)} due to quota constraints")
        except Exception:
            # Circuit Breaker 확인 실패 시 안전하게 제한
            max_individual_translations = min(len(japanese_texts), 10)
        
        results = []
        translated_count = 0
        
        for i, text in enumerate(japanese_texts):
            # 취소 확인
            if cancel_event and cancel_event.is_set():
                logger.info(f"Individual translation cancelled at {i}/{len(japanese_texts)}")
                # 나머지 텍스트는 취소 마크로 채움
                results.extend(["[번역 취소]"] * (len(japanese_texts) - i))
                break
            
            if text.strip() and translated_count < max_individual_translations:
                try:
                    translated = await self.translate_single(text)
                    results.append(translated)
                    translated_count += 1
                except Exception as e:
                    logger.warning(f"Individual translation failed for segment {i}: {e}")
                    results.append(f"[번역 실패] {text[:50]}...")
            else:
                # 할당량 제한으로 번역하지 않음
                if text.strip():
                    results.append(f"[할당량 제한] {text}")
                else:
                    results.append("")
        
        logger.info(f"Individual translation completed: {translated_count}/{len(japanese_texts)} successful")
        return results
    
    def _robust_segment_parsing(self, result: str, separator: str, expected_count: int) -> List[str]:
        """강화된 세그먼트 파싱 로직 (한국어 특화)"""
        if not result or not separator:
            return ["[파싱 오류]"] * expected_count
        
        # 1차: 기본 구분자 분할
        segments = result.split(separator)
        segments = [s.strip() for s in segments if s.strip()]
        
        # 정확한 개수가 나오면 바로 반환
        if len(segments) == expected_count:
            return segments
        
        # 2차: 줄바꿈 + 구분자 조합으로 분할
        alternative_patterns = [
            f"\n{separator}\n",
            f"\n{separator}",
            f"{separator}\n"
        ]
        
        for pattern in alternative_patterns:
            try:
                alt_segments = result.split(pattern)
                alt_segments = [s.strip() for s in alt_segments if s.strip() and s.strip() != separator]
                
                if len(alt_segments) == expected_count:
                    return alt_segments
            except Exception:
                continue
        
        # 3차: 개선된 한국어 문장 구분자 기반 분할
        korean_patterns = [
            r'[.!?。！？]\s*\n',                    # 문장부호 + 줄바꿈
            r'[다요]\s*[.!?]?\s*(?=\n|[가-힣]|$)',   # 한국어 어미 + 문장부호(선택) + 다음문장
            r'니다\s*[.!?]?\s*(?=\n|[가-힣]|$)',     # 존댓말 어미
            r'습니다\s*[.!?]?\s*(?=\n|[가-힣]|$)',   # 존댓말 어미 
            r'네요\s*[.!?]?\s*(?=\n|[가-힣]|$)',     # 감탄 어미
            r'죠\s*[.!?]?\s*(?=\n|[가-힣]|$)',       # 구어체 어미
            r'\n\s*(?=[가-힣])',                    # 줄바꿈 + 한글 시작
        ]
        
        for pattern in korean_patterns:
            try:
                korean_segments = re.split(pattern, result)
                korean_segments = [s.strip() for s in korean_segments if s.strip()]
                
                if len(korean_segments) == expected_count:
                    logger.info(f"Korean pattern matching successful with pattern: {pattern[:20]}...")
                    return korean_segments
                    
                # 개수가 비슷하면 후보로 저장
                if abs(len(korean_segments) - expected_count) <= 1:
                    segments = korean_segments
                    
            except Exception:
                continue
        
        # 4차: 단어 개수 기반 균등 분할 (fallback)
        if len(segments) != expected_count:
            words = result.split()
            if len(words) >= expected_count:
                words_per_segment = len(words) // expected_count
                remainder = len(words) % expected_count
                
                new_segments = []
                word_idx = 0
                for i in range(expected_count):
                    segment_word_count = words_per_segment + (1 if i < remainder else 0)
                    segment_words = words[word_idx:word_idx + segment_word_count]
                    new_segments.append(' '.join(segment_words) if segment_words else '[빈 세그먼트]')
                    word_idx += segment_word_count
                
                return new_segments
        
        # 최종: 길이 조정
        # 5차: 한국어 전용 분할 로직 시도
        korean_specific = self._korean_sentence_split(result, expected_count)
        if len(korean_specific) == expected_count:
            logger.info("Korean-specific segmentation successful")
            return korean_specific
        
        return self._adjust_segment_count(segments, expected_count)
    
    def _korean_sentence_split(self, text: str, expected_count: int) -> List[str]:
        """한국어 번역 결과 전용 문장 분할"""
        if not text or expected_count <= 1:
            return [text] if text else []
        
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
        
        # 각 패턴으로 분할 시도
        best_result = []
        best_score = float('inf')
        
        for pattern in korean_end_patterns:
            try:
                segments = re.split(pattern, text)
                segments = [s.strip() for s in segments if s.strip()]
                
                # 점수 계산 (예상 개수와의 차이 + 세그먼트 품질)
                count_diff = abs(len(segments) - expected_count)
                quality_score = sum(1 for s in segments if len(s) > 5 and not s.startswith('['))
                total_score = count_diff + (1 / max(quality_score, 1))
                
                if total_score < best_score:
                    best_score = total_score
                    best_result = segments
                    
                # 정확한 개수면 즉시 반환
                if len(segments) == expected_count:
                    logger.info(f"Perfect Korean split with pattern: {pattern[:30]}")
                    return segments
                    
            except Exception as e:
                logger.debug(f"Korean split pattern failed: {pattern[:20]} - {e}")
                continue
        
        # 최선의 결과가 있으면 반환
        if best_result and abs(len(best_result) - expected_count) <= 2:
            logger.info(f"Best Korean split: {len(best_result)} segments (expected {expected_count})")
            return best_result
        
        # 실패 시 원본 텍스트를 균등 분할
        words = text.split()
        if len(words) >= expected_count:
            chunk_size = len(words) // expected_count
            remainder = len(words) % expected_count
            
            result = []
            start_idx = 0
            for i in range(expected_count):
                end_idx = start_idx + chunk_size + (1 if i < remainder else 0)
                segment = ' '.join(words[start_idx:end_idx])
                result.append(segment if segment else '[분할 오류]')
                start_idx = end_idx
            
            logger.info(f"Korean fallback split: {len(result)} segments")
            return result
        
        return [text]  # 최종 fallback
    
    def _adjust_segment_count(self, segments: List[str], expected_count: int) -> List[str]:
        """세그먼트 개수를 예상 개수에 맞게 조정"""
        if len(segments) == expected_count:
            return segments
        elif len(segments) > expected_count:
            # 개수가 많으면 뒤쪽 세그먼트들을 마지막에 합치기
            result = segments[:expected_count-1]
            if expected_count > 0:
                combined_last = ' '.join(segments[expected_count-1:])
                result.append(combined_last)
            return result
        else:
            # 개수가 부족하면 빈 자리 채우기
            result = segments[:]
            while len(result) < expected_count:
                if segments:
                    # 마지막 세그먼트 복사 또는 연속 표시
                    result.append('[번역 연속]')
                else:
                    result.append('[번역 누락]')
            return result
    
    def _alternative_segment_parsing(self, result: str, expected_count: int) -> List[str]:
        """대안 파싱 방법"""
        # 문장 부호 기반 분할
        sentences = re.split(r'[。！？]', result)
        sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 3]
        
        if len(sentences) >= expected_count:
            return sentences[:expected_count]
        
        # 줄바꿈 기반 재분할
        lines = result.split('\n')
        valid_lines = [line.strip() for line in lines if line.strip() and len(line.strip()) > 3]
        
        if len(valid_lines) >= expected_count:
            return valid_lines[:expected_count]
        
        # 균등 분할
        if len(result) > expected_count * 10:
            chunk_size = len(result) // expected_count
            chunks = []
            for i in range(expected_count):
                start = i * chunk_size
                end = start + chunk_size if i < expected_count - 1 else len(result)
                chunks.append(result[start:end].strip())
            return chunks
        
        # 최후 수단: 동일 문장 반복 대신 안전한 채우기
        # 첫 세그먼트만 원문 유지, 나머지는 명시적 실패 표시로 채움
        fallback = [result.strip()] if result.strip() else []
        while len(fallback) < expected_count:
            fallback.append('[배치 파싱 실패]')
        return fallback[:expected_count]
    
    async def _retry_batch_translation(self, japanese_texts: List[str], cancel_event = None) -> List[str]:
        """배치 번역 재시도 (1회 제한)"""
        try:
            filtered_texts = [text.strip() for text in japanese_texts if text.strip()]
            if not filtered_texts:
                return [""] * len(japanese_texts)
            
            # 더 명확한 구분자 사용
            separator = "---NEXT_TRANSLATION---"
            combined_text = f"\n{separator}\n".join(filtered_texts)
            
            # 개선된 재시도 프롬프트 (문장 경계 보존 강화)
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

            일본어 원문:
            {japanese_text}

            한국어 번역:
            """)
            
            retry_chain = (
                retry_prompt
                | self.llm
                | StrOutputParser()
            )
            
            if cancel_event and cancel_event.is_set():
                return None
            
            result = await retry_chain.ainvoke({
                "japanese_text": combined_text,
                "separator": separator,
                "segment_count": len(filtered_texts)
            })
            
            # 파싱
            translated_segments = self._robust_segment_parsing(result.strip(), separator, len(filtered_texts))
            
            if len(translated_segments) == len(filtered_texts):
                # 원본 배열과 매칭
                result_list = []
                filtered_idx = 0
                for original_text in japanese_texts:
                    if original_text.strip():
                        result_list.append(translated_segments[filtered_idx].strip())
                        filtered_idx += 1
                    else:
                        result_list.append("")
                return result_list
            
            return None
            
        except Exception as e:
            logger.error(f"Batch translation retry failed: {e}")
            return None
    
    async def _limited_individual_translation(self, japanese_texts: List[str], max_individual: int = 10) -> List[str]:
        """제한적 개별 번역 (비용 절약) - 스마트 선택"""
        logger.info(f"Using limited individual translation (max {max_individual} out of {len(japanese_texts)})")
        
        # 번역할 텍스트 스마트 선택 (길이 기반 우선순위)
        indexed_texts = [(i, text) for i, text in enumerate(japanese_texts) if text.strip()]
        
        # 텍스트 길이를 기준으로 정렬 (중간 길이 우선 - 너무 짧거나 길지 않은)
        indexed_texts.sort(key=lambda x: abs(len(x[1]) - 50))  # 50자 내외를 우선
        
        # 실제 번역할 항목 선택
        to_translate = indexed_texts[:max_individual]
        
        results = [""] * len(japanese_texts)
        translated_count = 0
        
        for original_idx, text in to_translate:
            try:
                translated = await self.translate_single(text)
                results[original_idx] = translated
                translated_count += 1
                
                # 성공한 번역을 주변 빈 슬롯에도 유사한 형태로 적용
                if original_idx > 0 and not results[original_idx - 1]:
                    results[original_idx - 1] = f"[참조] {translated[:30]}..."
                if original_idx < len(results) - 1 and not results[original_idx + 1]:
                    results[original_idx + 1] = f"[참조] {translated[:30]}..."
                    
            except Exception as e:
                logger.warning(f"Limited translation failed for segment {original_idx}: {e}")
                results[original_idx] = f"[번역 실패] {text[:30]}..."
        
        # 번역되지 않은 텍스트들 처리
        for i, text in enumerate(japanese_texts):
            if not results[i] and text.strip():
                results[i] = f"[번역 제한] {text[:40]}..."
            elif not results[i]:
                results[i] = ""
        
        logger.info(f"Limited individual translation: {translated_count} translated, {len(japanese_texts) - translated_count} with fallback")
        return results
    
    async def translate_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """세그먼트 리스트 번역 (STT 결과 형식)"""
        if not segments:
            return []
        
        # 일본어 텍스트만 추출
        japanese_texts = [seg.get('text', '') for seg in segments]
        
        # 배치 번역 실행
        korean_translations = await self.translate_batch(japanese_texts)
        
        # 원본 세그먼트에 번역 결과 추가
        result_segments = []
        for i, segment in enumerate(segments):
            result_segment = segment.copy()
            if i < len(korean_translations):
                result_segment['korean_text'] = korean_translations[i]
            else:
                result_segment['korean_text'] = "[번역 누락]"
            result_segments.append(result_segment)
        
        return result_segments
    
    def get_agent_info(self) -> Dict[str, Any]:
        """에이전트 정보 반환"""
        return {
            "agent_type": "translator",
            "model_name": self.model_name,
            "temperature": self.temperature,
            "is_available": self.is_available(),
            "capabilities": ["single_translation", "batch_translation", "segment_translation"]
        }
