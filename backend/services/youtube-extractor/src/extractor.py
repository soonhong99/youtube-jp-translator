import os
import tempfile
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import yt_dlp
from pydub import AudioSegment

# import re
# import os

# def clean_filename(filename):
#     # 특수 문자 제거하고, 공백을 밑줄(_)로 변경
#     filename = re.sub(r'[^\w\s.-]', '', filename)
#     filename = filename.replace(" ", "_")
#     return filename

class YouTubeExtractor:
    """YouTube에서 오디오를 추출하고 STT 모델에 적합한 형식으로 변환하는 클래스"""
    
    def __init__(self, output_dir: Optional[str] = None, 
                 preferred_format: str = "wav", 
                 sample_rate: int = 16000,
                 channels: int = 1):
        """
        YouTubeExtractor 초기화
        
        Args:
            output_dir: 추출된 오디오 파일을 저장할 디렉토리 (None이면 임시 디렉토리 사용)
            preferred_format: 출력 오디오 형식 ('wav' 또는 'mp3')
            sample_rate: 출력 오디오의 샘플 레이트 (Hz)
            channels: 출력 오디오의 채널 수 (1=모노, 2=스테레오)
        """
        self.logger = logging.getLogger(__name__)
        
        # 출력 디렉토리 설정
        self.output_dir = output_dir
        if not self.output_dir:
            self.temp_dir = tempfile.TemporaryDirectory()
            self.output_dir = self.temp_dir.name
        else:
            self.temp_dir = None
            os.makedirs(self.output_dir, exist_ok=True)
            
        # 오디오 설정
        if preferred_format not in ["wav", "mp3"]:
            raise ValueError("지원되는 형식은 'wav'와 'mp3'입니다")
        self.preferred_format = preferred_format
        self.sample_rate = sample_rate
        self.channels = channels
    
    def __del__(self):
        """객체 소멸 시 임시 디렉토리 정리"""
        if hasattr(self, 'temp_dir') and self.temp_dir:
            self.temp_dir.cleanup()
    
    def extract_audio(self, youtube_url: str) -> Tuple[str, Dict[str, Any]]:
        """
        YouTube URL에서 오디오 추출
        
        Args:
            youtube_url: YouTube 동영상 URL
            
        Returns:
            Tuple[str, Dict]: (오디오 파일 경로, 비디오 정보)
        """
        self.logger.info(f"YouTube URL '{youtube_url}'에서 오디오 추출 시작")
        
        # 임시 다운로드 파일 이름 생성
        temp_download_path = os.path.join(self.output_dir, "temp_download.%(ext)s")
        
        # yt-dlp 옵션 설정
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_download_path,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': False,
            'no_warnings': False,
        }
        
        try:
            # 비디오 정보 가져오기 및 다운로드
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                video_info = ydl.sanitize_info(info)
            
            # 다운로드된 파일 경로 확인
            downloaded_file = os.path.join(self.output_dir, f"temp_download.mp3")
            
            # 최종 출력 파일 경로 생성
            video_title = video_info.get('title', 'unknown').replace('/', '_').replace('\\', '_')
            output_filename = f"{video_title}.{self.preferred_format}"
            output_path = os.path.join(self.output_dir, output_filename)
            
            # output_path = clean_filename(os.path.basename(output_path))

            # 필요한 경우 오디오 형식 변환
            self._convert_audio_format(downloaded_file, output_path)
            
            # 임시 다운로드 파일 삭제
            if os.path.exists(downloaded_file):
                os.remove(downloaded_file)
            
            self.logger.info(f"오디오 추출 완료: {output_path}")
            return output_path, video_info
            
        except Exception as e:
            self.logger.error(f"오디오 추출 중 오류 발생: {str(e)}")
            raise
    
    def _convert_audio_format(self, input_path: str, output_path: str) -> None:
        """
        오디오 파일을 STT 모델에 적합한 형식으로 변환
        
        Args:
            input_path: 입력 오디오 파일 경로
            output_path: 출력 오디오 파일 경로
        """
        try:
            # pydub을 사용하여 오디오 변환
            audio = AudioSegment.from_file(input_path)
            
            # 필요한 경우 채널 수 변환 (모노)
            if self.channels == 1 and audio.channels > 1:
                audio = audio.set_channels(1)
            
            # 샘플 레이트 변환
            if audio.frame_rate != self.sample_rate:
                audio = audio.set_frame_rate(self.sample_rate)
            
            # 파일 저장
            if self.preferred_format == 'wav':
                audio.export(output_path, format="wav", parameters=["-acodec", "pcm_s16le"])
            else:  # mp3
                audio.export(output_path, format="mp3", bitrate="192k")
                
            self.logger.info(f"오디오 변환 완료: {output_path}")
        
        except Exception as e:
            self.logger.error(f"오디오 변환 중 오류 발생: {str(e)}")
            raise
    
    def get_video_info(self, youtube_url: str) -> Dict[str, Any]:
        """
        YouTube 비디오 정보만 가져오기 (다운로드 없음)
        
        Args:
            youtube_url: YouTube 동영상 URL
            
        Returns:
            Dict: 비디오 정보
        """
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            return ydl.sanitize_info(info)