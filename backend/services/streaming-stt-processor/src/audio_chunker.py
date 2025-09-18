"""
Audio Chunker
5초 청크 + 1초 오버랩 방식의 오디오 분할 시스템
"""

import os
import logging
import tempfile
from typing import List, Dict, Tuple, Optional
import asyncio
from pathlib import Path
import io

import librosa
import soundfile as sf
import numpy as np
import time

logger = logging.getLogger(__name__)

class AudioChunker:
    """오디오 청킹 클래스"""

    def __init__(
        self,
        chunk_duration: float = 5.0,
        overlap_duration: float = 1.0,
        sample_rate: int = 16000
    ):
        self.chunk_duration = chunk_duration
        self.overlap_duration = overlap_duration
        self.sample_rate = sample_rate

        # 청크 크기 계산 (샘플 수)
        self.chunk_samples = int(chunk_duration * sample_rate)
        self.overlap_samples = int(overlap_duration * sample_rate)
        self.step_samples = self.chunk_samples - self.overlap_samples

        logger.info(f"🎵 AudioChunker 초기화: {chunk_duration}s 청크, {overlap_duration}s 오버랩")

    async def get_audio_duration(self, audio_file_path: str) -> float:
        """오디오 파일의 길이 반환"""
        try:
            # librosa는 비동기가 아니므로 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            duration = await loop.run_in_executor(
                None, self._get_duration_sync, audio_file_path
            )
            return duration
        except Exception as e:
            logger.error(f"❌ 오디오 길이 조회 실패: {e}")
            return 0.0

    def _get_duration_sync(self, audio_file_path: str) -> float:
        """동기적으로 오디오 길이 조회"""
        return librosa.get_duration(path=audio_file_path)

    async def create_chunks(
        self,
        audio_file_path: str,
        chunk_duration: float = None,
        overlap_duration: float = None,
        memory_mode: bool = True
    ) -> List[Dict[str, any]]:
        """오디오 파일을 청크로 분할 (메모리 기반 최적화)"""
        try:
            # 매개변수 설정
            chunk_dur = chunk_duration or self.chunk_duration
            overlap_dur = overlap_duration or self.overlap_duration

            logger.info(f"🔪 오디오 청킹 시작: {audio_file_path} (메모리 모드: {memory_mode})")

            # 비동기적으로 오디오 로드 및 청킹
            loop = asyncio.get_event_loop()
            if memory_mode:
                chunks = await loop.run_in_executor(
                    None,
                    self._create_chunks_memory_optimized,
                    audio_file_path,
                    chunk_dur,
                    overlap_dur
                )
            else:
                chunks = await loop.run_in_executor(
                    None,
                    self._create_chunks_sync,
                    audio_file_path,
                    chunk_dur,
                    overlap_dur
                )

            logger.info(f"✅ 청킹 완료: {len(chunks)}개 청크 생성")
            return chunks

        except Exception as e:
            logger.error(f"❌ 오디오 청킹 실패: {e}")
            return []

    def _create_chunks_sync(
        self,
        audio_file_path: str,
        chunk_duration: float,
        overlap_duration: float
    ) -> List[Dict[str, any]]:
        """동기적으로 오디오 청킹 수행"""
        chunks = []

        try:
            # 오디오 파일 로드
            audio_data, sr = librosa.load(
                audio_file_path,
                sr=self.sample_rate,
                mono=True
            )

            logger.info(f"📊 오디오 로드 완료: {len(audio_data)} 샘플, {sr}Hz")

            # 청크 설정 재계산
            chunk_samples = int(chunk_duration * sr)
            overlap_samples = int(overlap_duration * sr)
            step_samples = chunk_samples - overlap_samples

            # 청크 생성
            total_samples = len(audio_data)
            chunk_index = 0

            for start_sample in range(0, total_samples, step_samples):
                end_sample = min(start_sample + chunk_samples, total_samples)

                # 너무 짧은 청크: 마지막 조각이라도 최초 청크라면 1개는 생성하도록 허용
                if end_sample - start_sample < int(chunk_samples * 0.5):
                    if chunk_index == 0:
                        logger.debug("ℹ️ 전체 길이가 짧아도 최소 1개 청크를 생성합니다")
                    else:
                        logger.debug(f"⏭️ 짧은 청크 스킵: {end_sample - start_sample} 샘플")
                        break

                # 청크 데이터 추출
                chunk_data = audio_data[start_sample:end_sample]

                # 음성 활동 감지 (VAD)
                # 짧은 오디오의 경우 VAD가 너무 보수적일 수 있으므로
                # 첫 청크이면서 전체 길이가 매우 짧은 경우에는 VAD를 완화
                features = self._compute_audio_features(chunk_data)

                if self._has_speech_activity_from_features(features) or (chunk_index == 0 and total_samples < int(chunk_samples * 0.8)):
                    # 임시 파일로 저장
                    chunk_file_path = self._save_chunk_to_file(
                        chunk_data, sr, chunk_index
                    )

                    if chunk_file_path:
                        chunk_info = {
                            "chunk_index": chunk_index,
                            "file_path": chunk_file_path,
                            "start_time": start_sample / sr,
                            "end_time": end_sample / sr,
                            "duration": (end_sample - start_sample) / sr,
                            "start_sample": start_sample,
                            "end_sample": end_sample,
                            "has_overlap": chunk_index > 0,
                            "overlap_duration": overlap_duration if chunk_index > 0 else 0.0,
                            "rms": features["rms"],
                            "zcr": features["zcr"],
                        }

                        chunks.append(chunk_info)
                        chunk_index += 1

                        logger.debug(
                            f"📝 청크 {chunk_index}: "
                            f"{chunk_info['start_time']:.2f}s - {chunk_info['end_time']:.2f}s"
                        )
                else:
                    logger.debug(f"🔇 무음 청크 스킵: {start_sample/sr:.2f}s - {end_sample/sr:.2f}s")

            # 청크가 하나도 생성되지 않았다면 파일 전체를 하나의 청크로 만들어 반환 (VAD 우회)
            if not chunks and total_samples > 0:
                try:
                    chunk_file_path = self._save_chunk_to_file(audio_data, sr, 0)
                    if chunk_file_path:
                        features = self._compute_audio_features(audio_data)
                        chunks.append({
                            "chunk_index": 0,
                            "file_path": chunk_file_path,
                            "start_time": 0.0,
                            "end_time": total_samples / sr,
                            "duration": total_samples / sr,
                            "start_sample": 0,
                            "end_sample": total_samples,
                            "has_overlap": False,
                            "overlap_duration": 0.0,
                            "rms": features["rms"],
                            "zcr": features["zcr"],
                        })
                        logger.debug("ℹ️ VAD 우회: 전체 파일을 단일 청크로 생성")
                except Exception as e:
                    logger.warning(f"⚠️ 단일 청크 생성 실패: {e}")

            return chunks

        except Exception as e:
            logger.error(f"❌ 동기 청킹 실패: {e}")
            return []

    def _create_chunks_memory_optimized(
        self,
        audio_file_path: str,
        chunk_duration: float,
        overlap_duration: float
    ) -> List[Dict[str, any]]:
        """메모리 기반 최적화된 청킹 (디스크 I/O 제거)"""
        chunks = []

        try:
            # 오디오 파일 로드
            audio_data, sr = librosa.load(
                audio_file_path,
                sr=self.sample_rate,
                mono=True
            )

            logger.info(f"📊 오디오 로드 완료: {len(audio_data)} 샘플, {sr}Hz")

            # 청크 설정 재계산
            chunk_samples = int(chunk_duration * sr)
            overlap_samples = int(overlap_duration * sr)
            step_samples = chunk_samples - overlap_samples

            # 청크 생성
            total_samples = len(audio_data)
            chunk_index = 0

            for start_sample in range(0, total_samples, step_samples):
                end_sample = min(start_sample + chunk_samples, total_samples)

                # 너무 짧은 청크 처리
                if end_sample - start_sample < int(chunk_samples * 0.5):
                    if chunk_index == 0:
                        logger.debug("ℹ️ 전체 길이가 짧아도 최소 1개 청크를 생성합니다")
                    else:
                        logger.debug(f"⏭️ 짧은 청크 스킵: {end_sample - start_sample} 샘플")
                        break

                # 청크 데이터 추출 (메모리에 보관)
                chunk_data = audio_data[start_sample:end_sample]
                features = self._compute_audio_features(chunk_data)

                # 음성 활동 감지
                if self._has_speech_activity_from_features(features) or (chunk_index == 0 and total_samples < int(chunk_samples * 0.8)):
                    # 메모리 기반 청크 정보 생성
                    chunk_info = {
                        "chunk_index": chunk_index,
                        "audio_data": chunk_data,  # 메모리에 저장
                        "sample_rate": sr,
                        "start_time": start_sample / sr,
                        "end_time": end_sample / sr,
                        "duration": (end_sample - start_sample) / sr,
                        "start_sample": start_sample,
                        "end_sample": end_sample,
                        "has_overlap": chunk_index > 0,
                        "overlap_duration": overlap_duration if chunk_index > 0 else 0.0,
                        "rms": features["rms"],
                        "zcr": features["zcr"],
                        "memory_mode": True
                    }

                    chunks.append(chunk_info)
                    chunk_index += 1

                    logger.debug(
                        f"📝 청크 {chunk_index}: "
                        f"{chunk_info['start_time']:.2f}s - {chunk_info['end_time']:.2f}s (메모리)"
                    )
                else:
                    logger.debug(f"🔇 무음 청크 스킵: {start_sample/sr:.2f}s - {end_sample/sr:.2f}s")

            # 청크가 하나도 생성되지 않았다면 파일 전체를 하나의 청크로 만들어 반환
            if not chunks and total_samples > 0:
                features = self._compute_audio_features(audio_data)
                chunks.append({
                    "chunk_index": 0,
                    "audio_data": audio_data,
                    "sample_rate": sr,
                    "start_time": 0.0,
                    "end_time": total_samples / sr,
                    "duration": total_samples / sr,
                    "start_sample": 0,
                    "end_sample": total_samples,
                    "has_overlap": False,
                    "overlap_duration": 0.0,
                    "memory_mode": True,
                    "rms": features["rms"],
                    "zcr": features["zcr"]
                })
                logger.debug("ℹ️ VAD 우회: 전체 파일을 단일 청크로 생성 (메모리)")

            return chunks

        except Exception as e:
            logger.error(f"❌ 메모리 최적화 청킹 실패: {e}")
            return []

    def _compute_audio_features(self, audio_data: np.ndarray) -> Dict[str, float]:
        """청크의 기본 오디오 특징(RMS/ZCR) 계산"""
        if len(audio_data) == 0:
            return {"rms": 0.0, "zcr": 0.0}

        rms_energy = float(np.sqrt(np.mean(audio_data ** 2)))
        zero_crossings = np.sum(np.diff(np.signbit(audio_data)))
        zcr = float(zero_crossings / len(audio_data))

        return {"rms": rms_energy, "zcr": zcr}

    def _has_speech_activity_from_features(
        self,
        features: Dict[str, float],
        energy_threshold: float = 0.01,
        zcr_threshold: float = 0.01
    ) -> bool:
        """사전 계산된 특징으로 음성 활동 여부 판정"""
        return (
            features.get("rms", 0.0) > energy_threshold and
            features.get("zcr", 0.0) > zcr_threshold
        )

    def _save_chunk_to_file(
        self,
        chunk_data: np.ndarray,
        sample_rate: int,
        chunk_index: int
    ) -> str:
        """청크를 임시 파일로 저장"""
        try:
            # 임시 디렉토리 생성
            temp_dir = Path(tempfile.gettempdir()) / "streaming_stt_chunks"
            temp_dir.mkdir(exist_ok=True)

            # 임시 파일 경로
            # Use wall-clock time since this may run in a thread without an event loop
            chunk_filename = f"chunk_{chunk_index}_{int(time.time())}.wav"
            chunk_file_path = temp_dir / chunk_filename

            # WAV 파일로 저장
            sf.write(
                str(chunk_file_path),
                chunk_data,
                sample_rate,
                format='WAV',
                subtype='PCM_16'
            )

            return str(chunk_file_path)

        except Exception as e:
            logger.error(f"❌ 청크 파일 저장 실패: {e}")
            return None

    async def cleanup_chunks(self, chunks: List[Dict[str, any]]):
        """청크 파일들 정리 (메모리 모드 고려)"""
        try:
            file_count = 0
            memory_count = 0

            for chunk in chunks:
                if chunk.get("memory_mode", False):
                    # 메모리 기반 청크는 가비지 컬렉션에 맡김
                    chunk.pop("audio_data", None)
                    memory_count += 1
                else:
                    # 파일 기반 청크는 파일 삭제
                    file_path = chunk.get("file_path")
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            logger.debug(f"🗑️ 청크 파일 삭제: {file_path}")
                            file_count += 1
                        except Exception as e:
                            logger.warning(f"⚠️ 청크 파일 삭제 실패: {e}")

            logger.info(f"✅ 청크 정리 완료: {file_count}개 파일, {memory_count}개 메모리 청크")

        except Exception as e:
            logger.error(f"❌ 청크 정리 실패: {e}")

    async def validate_audio_file(self, audio_file_path: str) -> Tuple[bool, str]:
        """오디오 파일 검증"""
        try:
            if not os.path.exists(audio_file_path):
                return False, "파일이 존재하지 않습니다"

            # 파일 크기 확인
            file_size = os.path.getsize(audio_file_path)
            if file_size == 0:
                return False, "빈 파일입니다"

            # 오디오 파일 포맷 확인
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(
                    None, librosa.load, audio_file_path, {"sr": None, "duration": 1}
                )
            except Exception as e:
                return False, f"유효하지 않은 오디오 파일: {str(e)}"

            return True, "유효한 오디오 파일"

        except Exception as e:
            return False, f"파일 검증 실패: {str(e)}"

    def get_chunk_info(self, total_duration: float) -> Dict[str, any]:
        """청킹 정보 계산"""
        if total_duration <= 0:
            return {}

        estimated_chunks = max(1, int(
            (total_duration - self.overlap_duration) /
            (self.chunk_duration - self.overlap_duration)
        ))

        return {
            "total_duration": total_duration,
            "chunk_duration": self.chunk_duration,
            "overlap_duration": self.overlap_duration,
            "estimated_chunks": estimated_chunks,
            "estimated_processing_time_sequential": estimated_chunks * 0.8,  # 순차 처리시
            "estimated_processing_time_parallel": max(1, estimated_chunks // 3) * 0.8  # 병렬 처리시 (3개 모델)
        }
