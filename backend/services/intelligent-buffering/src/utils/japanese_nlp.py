"""
일본어 자연어 처리 유틸리티
"""

import re
import logging
from typing import List, Dict, Tuple, Optional
import spacy
import MeCab
try:
    from sudachipy import tokenizer_obj, dictionary
except ImportError:
    # Fallback import for newer versions of sudachipy
    try:
        from sudachipy import Dictionary
        dictionary = Dictionary()
        tokenizer_obj = dictionary.create()
    except ImportError:
        dictionary = None
        tokenizer_obj = None

logger = logging.getLogger(__name__)

class JapaneseNLPProcessor:
    """일본어 자연어 처리 클래스"""

    def __init__(self):
        try:
            # spaCy 일본어 모델 로드
            self.nlp = spacy.load("ja_core_news_sm")
            logger.info("✅ spaCy 일본어 모델 로드 완료")
        except Exception as e:
            logger.warning(f"⚠️ spaCy 모델 로드 실패: {e}")
            self.nlp = None

        try:
            # MeCab 초기화
            self.mecab = MeCab.Tagger("-Owakati")
            logger.info("✅ MeCab 초기화 완료")
        except Exception as e:
            logger.warning(f"⚠️ MeCab 초기화 실패: {e}")
            self.mecab = None

        try:
            # Sudachi 초기화
            self.sudachi_tokenizer = dictionary.Dictionary().create()
            logger.info("✅ Sudachi 초기화 완료")
        except Exception as e:
            logger.warning(f"⚠️ Sudachi 초기화 실패: {e}")
            self.sudachi_tokenizer = None

        # 일본어 문장 부호 패턴
        self.sentence_endings = re.compile(r'[。！？．!?]')
        self.partial_endings = re.compile(r'[、，,]')
        self.quotation_marks = re.compile(r'[「」『』""''（）()]')

    def analyze_morphemes(self, text: str) -> List[Dict]:
        """형태소 분석"""
        morphemes = []

        try:
            if self.sudachi_tokenizer:
                # Sudachi 사용
                tokens = self.sudachi_tokenizer.tokenize(text)
                for token in tokens:
                    morphemes.append({
                        'surface': token.surface(),
                        'reading': token.reading_form(),
                        'part_of_speech': token.part_of_speech()[0],
                        'sub_pos': token.part_of_speech()[1] if len(token.part_of_speech()) > 1 else '',
                        'base_form': token.dictionary_form(),
                        'feature': ','.join(token.part_of_speech())
                    })

            elif self.nlp:
                # spaCy 백업
                doc = self.nlp(text)
                for token in doc:
                    morphemes.append({
                        'surface': token.text,
                        'reading': token.norm_,
                        'part_of_speech': token.pos_,
                        'sub_pos': token.tag_,
                        'base_form': token.lemma_,
                        'feature': f"{token.pos_},{token.tag_}"
                    })

        except Exception as e:
            logger.error(f"❌ 형태소 분석 실패: {e}")

        return morphemes

    def detect_sentence_boundaries(self, text: str) -> List[Tuple[int, int, str]]:
        """문장 경계 감지"""
        boundaries = []

        # 문장 종료 부호 찾기
        for match in self.sentence_endings.finditer(text):
            boundaries.append((match.start(), match.end(), 'sentence_end'))

        # 부분 종료 부호 찾기
        for match in self.partial_endings.finditer(text):
            boundaries.append((match.start(), match.end(), 'partial_end'))

        # 정렬
        boundaries.sort(key=lambda x: x[0])
        return boundaries

    def calculate_grammar_completeness(self, text: str) -> float:
        """문법적 완성도 계산"""
        try:
            if not text.strip():
                return 0.0

            score = 0.0
            factors = []

            # 1. 문장 종료 부호 확인 (40점)
            if self.sentence_endings.search(text):
                score += 0.4
                factors.append("문장_종료_부호")

            # 2. 주어-술어 구조 확인 (30점)
            if self._has_subject_predicate_structure(text):
                score += 0.3
                factors.append("주술_구조")

            # 3. 완전한 구문 구조 (20점)
            if self._has_complete_phrase_structure(text):
                score += 0.2
                factors.append("완전_구문")

            # 4. 조사 활용 적절성 (10점)
            if self._has_proper_particles(text):
                score += 0.1
                factors.append("조사_활용")

            logger.debug(f"문법 완성도: {score:.2f}, 요인: {factors}")
            return min(1.0, score)

        except Exception as e:
            logger.error(f"❌ 문법 완성도 계산 실패: {e}")
            return 0.0

    def _has_subject_predicate_structure(self, text: str) -> bool:
        """주어-술어 구조 확인"""
        try:
            morphemes = self.analyze_morphemes(text)

            has_subject = False
            has_predicate = False

            for morpheme in morphemes:
                pos = morpheme.get('part_of_speech', '')

                # 주어 확인 (명사 + は/が)
                if pos in ['NOUN', '名詞'] and any(
                    particle in morpheme.get('feature', '')
                    for particle in ['は', 'が', 'も']
                ):
                    has_subject = True

                # 술어 확인 (동사, 형용사, 형용동사)
                if pos in ['VERB', 'ADJ', '動詞', '形容詞', '形容動詞']:
                    has_predicate = True

            return has_subject and has_predicate

        except Exception:
            return False

    def _has_complete_phrase_structure(self, text: str) -> bool:
        """완전한 구문 구조 확인"""
        try:
            # 기본적인 구문 패턴 확인
            patterns = [
                r'.*[はがを].*[だである]',  # 기본 문형
                r'.*[はがを].*[です]',      # 정중 문형
                r'.*[てで].*[いる]',       # 진행형
                r'.*[た]$',                # 과거형
            ]

            for pattern in patterns:
                if re.search(pattern, text):
                    return True

            return False

        except Exception:
            return False

    def _has_proper_particles(self, text: str) -> bool:
        """조사 활용 적절성 확인"""
        try:
            morphemes = self.analyze_morphemes(text)

            # 기본 조사들의 적절한 사용 확인
            particles_found = []
            for morpheme in morphemes:
                pos = morpheme.get('part_of_speech', '')
                if pos in ['ADP', '助詞']:
                    particles_found.append(morpheme.get('surface', ''))

            # 기본 조사가 하나 이상 있으면 적절하다고 판단
            basic_particles = ['は', 'が', 'を', 'に', 'へ', 'と', 'で', 'から', 'まで']
            return any(particle in particles_found for particle in basic_particles)

        except Exception:
            return False

    def calculate_semantic_completeness(self, text: str) -> float:
        """의미적 완성도 계산"""
        try:
            if not text.strip():
                return 0.0

            score = 0.0

            # 1. 의미 있는 단어 밀도 (40점)
            content_word_ratio = self._calculate_content_word_ratio(text)
            score += content_word_ratio * 0.4

            # 2. 문맥적 일관성 (30점)
            coherence_score = self._calculate_coherence(text)
            score += coherence_score * 0.3

            # 3. 정보 완전성 (30점)
            information_completeness = self._calculate_information_completeness(text)
            score += information_completeness * 0.3

            return min(1.0, score)

        except Exception as e:
            logger.error(f"❌ 의미적 완성도 계산 실패: {e}")
            return 0.0

    def _calculate_content_word_ratio(self, text: str) -> float:
        """내용어 비율 계산"""
        try:
            morphemes = self.analyze_morphemes(text)
            if not morphemes:
                return 0.0

            content_words = 0
            total_words = len(morphemes)

            for morpheme in morphemes:
                pos = morpheme.get('part_of_speech', '')
                if pos in ['NOUN', 'VERB', 'ADJ', '名詞', '動詞', '形容詞']:
                    content_words += 1

            return content_words / total_words if total_words > 0 else 0.0

        except Exception:
            return 0.0

    def _calculate_coherence(self, text: str) -> float:
        """문맥적 일관성 계산"""
        try:
            # 간단한 일관성 검사
            # 실제로는 더 복잡한 임베딩 기반 분석이 필요

            # 반복 패턴 확인
            words = text.split()
            if len(set(words)) < len(words) * 0.5:  # 50% 이상 반복
                return 0.3

            # 기본적인 문맥 연결어 확인
            connectives = ['そして', 'しかし', 'でも', 'ところで', 'それで', 'だから']
            if any(conn in text for conn in connectives):
                return 0.8

            return 0.6  # 기본값

        except Exception:
            return 0.5

    def _calculate_information_completeness(self, text: str) -> float:
        """정보 완전성 계산"""
        try:
            # 5W1H 요소 확인
            question_words = ['誰', 'だれ', '何', 'なに', 'なん', 'いつ', 'どこ', 'なぜ', 'どう']

            # 정보 제공 패턴 확인
            information_patterns = [
                r'\d+',  # 숫자
                r'[年月日時分秒]',  # 시간 표현
                r'[場所地点]',  # 장소 표현
            ]

            score = 0.5  # 기본값

            # 구체적인 정보가 있으면 가점
            for pattern in information_patterns:
                if re.search(pattern, text):
                    score += 0.1

            # 의문문이 있으면 완전성 감점
            if any(qword in text for qword in question_words):
                score -= 0.2

            return max(0.0, min(1.0, score))

        except Exception:
            return 0.5

    def calculate_punctuation_score(self, text: str) -> float:
        """문장 부호 점수 계산"""
        try:
            if not text.strip():
                return 0.0

            score = 0.0

            # 1. 문장 종료 부호 (60점)
            if self.sentence_endings.search(text):
                score += 0.6

            # 2. 적절한 쉼표 사용 (20점)
            comma_count = len(self.partial_endings.findall(text))
            text_length = len(text)
            if text_length > 20 and comma_count > 0:
                # 적절한 쉼표 사용 비율
                comma_ratio = comma_count / (text_length / 20)
                score += min(0.2, comma_ratio * 0.2)

            # 3. 인용부호 균형 (20점)
            quote_balance = self._check_quote_balance(text)
            score += quote_balance * 0.2

            return min(1.0, score)

        except Exception as e:
            logger.error(f"❌ 문장 부호 점수 계산 실패: {e}")
            return 0.0

    def _check_quote_balance(self, text: str) -> float:
        """인용부호 균형 확인"""
        try:
            quote_pairs = [('「', '」'), ('『', '』'), ('"', '"'), ("'", "'"), ('（', '）')]

            total_balance = 0.0
            pair_count = 0

            for open_quote, close_quote in quote_pairs:
                open_count = text.count(open_quote)
                close_count = text.count(close_quote)

                if open_count > 0 or close_count > 0:
                    pair_count += 1
                    balance = 1.0 - abs(open_count - close_count) / max(open_count + close_count, 1)
                    total_balance += balance

            return total_balance / pair_count if pair_count > 0 else 1.0

        except Exception:
            return 1.0

    def extract_topic_keywords(self, text: str, top_k: int = 5) -> List[str]:
        """주제 키워드 추출"""
        try:
            morphemes = self.analyze_morphemes(text)

            # 명사만 추출
            nouns = [
                morpheme['base_form'] for morpheme in morphemes
                if morpheme.get('part_of_speech') in ['NOUN', '名詞']
                and len(morpheme.get('surface', '')) > 1  # 한 글자 제외
            ]

            # 빈도 계산
            from collections import Counter
            noun_freq = Counter(nouns)

            # 상위 키워드 반환
            return [noun for noun, freq in noun_freq.most_common(top_k)]

        except Exception as e:
            logger.error(f"❌ 주제 키워드 추출 실패: {e}")
            return []

    def detect_grammar_issues(self, text: str) -> List[str]:
        """문법 문제점 감지"""
        issues = []

        try:
            # 1. 문장 종료 부호 누락
            if not self.sentence_endings.search(text) and len(text) > 10:
                issues.append("문장_종료_부호_누락")

            # 2. 조사 누락 가능성
            if not self._has_proper_particles(text):
                issues.append("조사_사용_부족")

            # 3. 주술 구조 미완성
            if not self._has_subject_predicate_structure(text):
                issues.append("주술_구조_미완성")

            # 4. 인용부호 불균형
            if self._check_quote_balance(text) < 0.8:
                issues.append("인용부호_불균형")

        except Exception as e:
            logger.error(f"❌ 문법 문제점 감지 실패: {e}")

        return issues