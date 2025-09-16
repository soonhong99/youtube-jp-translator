"""
오디오 분석 유틸리티
"""

import logging
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import asdict

from ..models.context_models import AudioFeatures, SpeakerChange, SpeakerChangeConfidence

logger = logging.getLogger(__name__)

class AudioAnalyzer:
    """오디오 특성 분석 클래스"""

    def __init__(self):
        """초기화"""
        try:
            # librosa 로드 시도
            import librosa
            self.librosa = librosa
            self.librosa_available = True
            logger.info("✅ librosa 로드 완료")
        except ImportError:
            logger.warning("⚠️ librosa 없음 - 기본 분석만 가능")
            self.librosa = None
            self.librosa_available = False

        # 화자 변경 감지 임계값
        self.speaker_change_thresholds = {
            'pitch_threshold': 20.0,      # Hz
            'energy_threshold': 0.3,      # dB 비율
            'pause_threshold': 0.5,       # 초
            'spectral_threshold': 0.2     # 스펙트럴 변화
        }

    def extract_audio_features(self, audio_data: np.ndarray,
                             sample_rate: int = 16000) -> AudioFeatures:
        """오디오 특성 추출"""
        try:
            if not self.librosa_available:
                return self._extract_basic_features(audio_data)

            # librosa를 사용한 고급 특성 추출
            features = AudioFeatures()

            # 1. 피치 특성
            pitches, magnitudes = self.librosa.piptrack(
                y=audio_data, sr=sample_rate, threshold=0.1
            )
            pitch_values = []
            for t in range(pitches.shape[1]):
                index = magnitudes[:, t].argmax()
                pitch = pitches[index, t]
                if pitch > 0:
                    pitch_values.append(pitch)

            if pitch_values:
                features.pitch_mean = np.mean(pitch_values)
                features.pitch_variance = np.var(pitch_values)

            # 2. 에너지 특성
            energy = np.sum(audio_data ** 2, axis=0) if len(audio_data.shape) > 1 else audio_data ** 2
            if len(energy) > 1:
                features.energy_mean = np.mean(energy)
                features.energy_variance = np.var(energy)
            else:
                features.energy_mean = float(energy) if np.isscalar(energy) else energy.item()
                features.energy_variance = 0.0

            # 3. 스펙트럴 특성
            spectral_centroids = self.librosa.feature.spectral_centroid(
                y=audio_data, sr=sample_rate
            )[0]
            features.spectral_centroid = np.mean(spectral_centroids)

            # 4. 영교차율
            zcr = self.librosa.feature.zero_crossing_rate(audio_data)[0]
            features.zero_crossing_rate = np.mean(zcr)

            # 5. MFCC 특성
            mfccs = self.librosa.feature.mfcc(
                y=audio_data, sr=sample_rate, n_mfcc=13
            )
            features.mfcc_features = np.mean(mfccs, axis=1).tolist()

            logger.debug("✅ 오디오 특성 추출 완료")
            return features

        except Exception as e:
            logger.error(f"❌ 오디오 특성 추출 실패: {e}")
            return self._extract_basic_features(audio_data)

    def _extract_basic_features(self, audio_data: np.ndarray) -> AudioFeatures:
        """기본 특성 추출 (librosa 없이)"""
        try:
            features = AudioFeatures()

            # 기본 에너지 계산
            if len(audio_data) > 0:
                energy_values = audio_data ** 2
                features.energy_mean = float(np.mean(energy_values))
                features.energy_variance = float(np.var(energy_values))

                # 간단한 영교차율
                zero_crossings = np.diff(np.signbit(audio_data)).sum()
                features.zero_crossing_rate = zero_crossings / len(audio_data)

            return features

        except Exception as e:
            logger.error(f"❌ 기본 특성 추출 실패: {e}")
            return AudioFeatures()

    def detect_speaker_changes(self, audio_segments: List[Tuple[np.ndarray, float, float]],
                             sample_rate: int = 16000) -> List[SpeakerChange]:
        """화자 변경 감지"""
        try:
            if len(audio_segments) < 2:
                return []

            speaker_changes = []
            prev_features = None

            for i, (audio_data, start_time, end_time) in enumerate(audio_segments):
                # 현재 세그먼트의 특성 추출
                current_features = self.extract_audio_features(audio_data, sample_rate)

                if prev_features is not None:
                    # 화자 변경 가능성 분석
                    change_analysis = self._analyze_speaker_change(
                        prev_features, current_features, start_time
                    )

                    if change_analysis['is_change']:
                        speaker_change = SpeakerChange(
                            timestamp=start_time,
                            confidence=change_analysis['confidence'],
                            confidence_level=change_analysis['confidence_level'],
                            audio_features_diff=change_analysis['features_diff'],
                            pause_duration=change_analysis.get('pause_duration', 0.0),
                            volume_change=change_analysis.get('volume_change', 0.0)
                        )
                        speaker_changes.append(speaker_change)

                prev_features = current_features

            logger.debug(f"✅ 화자 변경 감지 완료: {len(speaker_changes)}개 발견")
            return speaker_changes

        except Exception as e:
            logger.error(f"❌ 화자 변경 감지 실패: {e}")
            return []

    def _analyze_speaker_change(self, prev_features: AudioFeatures,
                              current_features: AudioFeatures,
                              timestamp: float) -> Dict:
        """화자 변경 분석"""
        try:
            analysis = {
                'is_change': False,
                'confidence': 0.0,
                'confidence_level': SpeakerChangeConfidence.LOW,
                'features_diff': 0.0
            }

            # 1. 피치 변화 분석
            pitch_diff = 0.0
            if prev_features.pitch_mean > 0 and current_features.pitch_mean > 0:
                pitch_diff = abs(prev_features.pitch_mean - current_features.pitch_mean)

            # 2. 에너지 변화 분석
            energy_diff = 0.0
            if prev_features.energy_mean > 0 and current_features.energy_mean > 0:
                energy_ratio = current_features.energy_mean / prev_features.energy_mean
                energy_diff = abs(1.0 - energy_ratio)

            # 3. 스펙트럴 변화 분석
            spectral_diff = abs(
                prev_features.spectral_centroid - current_features.spectral_centroid
            )

            # 4. 종합 특성 차이 계산
            features_diff = (
                (pitch_diff / 100.0) * 0.4 +  # 피치 정규화 후 가중치
                energy_diff * 0.3 +            # 에너지 차이
                (spectral_diff / 1000.0) * 0.3 # 스펙트럴 차이 정규화 후 가중치
            )

            analysis['features_diff'] = features_diff

            # 5. 변경 임계값 확인
            change_indicators = 0
            confidence_score = 0.0

            if pitch_diff > self.speaker_change_thresholds['pitch_threshold']:
                change_indicators += 1
                confidence_score += 0.3

            if energy_diff > self.speaker_change_thresholds['energy_threshold']:
                change_indicators += 1
                confidence_score += 0.2

            if features_diff > 0.3:  # 종합 차이 임계값
                change_indicators += 1
                confidence_score += 0.3

            # 추가 분석 (MFCC 비교)
            if (prev_features.mfcc_features and current_features.mfcc_features and
                len(prev_features.mfcc_features) == len(current_features.mfcc_features)):

                mfcc_diff = np.mean([
                    abs(prev - curr) for prev, curr in
                    zip(prev_features.mfcc_features, current_features.mfcc_features)
                ])

                if mfcc_diff > 0.2:
                    change_indicators += 1
                    confidence_score += 0.2

            # 6. 최종 판정
            if change_indicators >= 2:
                analysis['is_change'] = True
                analysis['confidence'] = min(1.0, confidence_score)

                if analysis['confidence'] >= 0.7:
                    analysis['confidence_level'] = SpeakerChangeConfidence.HIGH
                elif analysis['confidence'] >= 0.4:
                    analysis['confidence_level'] = SpeakerChangeConfidence.MEDIUM
                else:
                    analysis['confidence_level'] = SpeakerChangeConfidence.LOW

            return analysis

        except Exception as e:
            logger.error(f"❌ 화자 변경 분석 실패: {e}")
            return {
                'is_change': False,
                'confidence': 0.0,
                'confidence_level': SpeakerChangeConfidence.LOW,
                'features_diff': 0.0
            }

    def calculate_audio_similarity(self, features1: AudioFeatures,
                                 features2: AudioFeatures) -> float:
        """오디오 특성 유사도 계산"""
        try:
            similarity_scores = []

            # 1. 피치 유사도
            if features1.pitch_mean > 0 and features2.pitch_mean > 0:
                pitch_diff = abs(features1.pitch_mean - features2.pitch_mean)
                pitch_similarity = max(0.0, 1.0 - pitch_diff / 100.0)  # 100Hz 정규화
                similarity_scores.append(pitch_similarity * 0.3)

            # 2. 에너지 유사도
            if features1.energy_mean > 0 and features2.energy_mean > 0:
                energy_ratio = min(features1.energy_mean, features2.energy_mean) / \
                              max(features1.energy_mean, features2.energy_mean)
                similarity_scores.append(energy_ratio * 0.2)

            # 3. 스펙트럴 유사도
            spectral_diff = abs(features1.spectral_centroid - features2.spectral_centroid)
            spectral_similarity = max(0.0, 1.0 - spectral_diff / 1000.0)  # 1000Hz 정규화
            similarity_scores.append(spectral_similarity * 0.2)

            # 4. MFCC 유사도
            if (features1.mfcc_features and features2.mfcc_features and
                len(features1.mfcc_features) == len(features2.mfcc_features)):

                mfcc_similarity = 1.0 - np.mean([
                    abs(f1 - f2) for f1, f2 in
                    zip(features1.mfcc_features, features2.mfcc_features)
                ])
                similarity_scores.append(max(0.0, mfcc_similarity) * 0.3)

            # 전체 유사도 계산
            if similarity_scores:
                total_similarity = sum(similarity_scores)
                return min(1.0, max(0.0, total_similarity))
            else:
                return 0.5  # 기본값

        except Exception as e:
            logger.error(f"❌ 오디오 유사도 계산 실패: {e}")
            return 0.5

    def detect_silence_regions(self, audio_data: np.ndarray,
                             sample_rate: int = 16000,
                             silence_threshold: float = 0.01,
                             min_silence_duration: float = 0.1) -> List[Tuple[float, float]]:
        """무음 구간 감지"""
        try:
            # 에너지 계산
            frame_length = int(sample_rate * 0.025)  # 25ms 프레임
            hop_length = int(sample_rate * 0.010)    # 10ms 홉

            energy = []
            for i in range(0, len(audio_data) - frame_length, hop_length):
                frame = audio_data[i:i + frame_length]
                frame_energy = np.sum(frame ** 2) / len(frame)
                energy.append(frame_energy)

            energy = np.array(energy)

            # 무음 구간 찾기
            silence_frames = energy < silence_threshold
            silence_regions = []

            in_silence = False
            silence_start = 0

            for i, is_silent in enumerate(silence_frames):
                time_pos = i * hop_length / sample_rate

                if is_silent and not in_silence:
                    # 무음 시작
                    silence_start = time_pos
                    in_silence = True
                elif not is_silent and in_silence:
                    # 무음 종료
                    silence_duration = time_pos - silence_start
                    if silence_duration >= min_silence_duration:
                        silence_regions.append((silence_start, time_pos))
                    in_silence = False

            # 마지막 무음 구간 처리
            if in_silence:
                final_time = len(energy) * hop_length / sample_rate
                silence_duration = final_time - silence_start
                if silence_duration >= min_silence_duration:
                    silence_regions.append((silence_start, final_time))

            logger.debug(f"✅ 무음 구간 감지 완료: {len(silence_regions)}개 발견")
            return silence_regions

        except Exception as e:
            logger.error(f"❌ 무음 구간 감지 실패: {e}")
            return []

    def analyze_prosodic_features(self, audio_data: np.ndarray,
                                sample_rate: int = 16000) -> Dict:
        """운율 특성 분석"""
        try:
            if not self.librosa_available:
                return {}

            prosody = {}

            # 1. 피치 윤곽 분석
            pitches, magnitudes = self.librosa.piptrack(
                y=audio_data, sr=sample_rate, threshold=0.1
            )

            pitch_contour = []
            for t in range(pitches.shape[1]):
                index = magnitudes[:, t].argmax()
                pitch = pitches[index, t]
                if pitch > 0:
                    pitch_contour.append(pitch)

            if pitch_contour:
                prosody['pitch_range'] = max(pitch_contour) - min(pitch_contour)
                prosody['pitch_variance'] = np.var(pitch_contour)
                prosody['pitch_slope'] = np.polyfit(range(len(pitch_contour)), pitch_contour, 1)[0]

            # 2. 리듬 분석
            tempo, beats = self.librosa.beat.beat_track(y=audio_data, sr=sample_rate)
            prosody['tempo'] = float(tempo)
            prosody['beat_count'] = len(beats)

            # 3. 강세 패턴 분석
            rms_energy = self.librosa.feature.rms(y=audio_data)[0]
            prosody['energy_variance'] = float(np.var(rms_energy))
            prosody['dynamic_range'] = float(np.max(rms_energy) - np.min(rms_energy))

            logger.debug("✅ 운율 특성 분석 완료")
            return prosody

        except Exception as e:
            logger.error(f"❌ 운율 특성 분석 실패: {e}")
            return {}