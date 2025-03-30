"""YouTube audio extractor module.

This module provides functionality to extract audio from YouTube videos.
"""

import os
import uuid
from typing import Optional, Tuple

import pytube
from pydub import AudioSegment

from config.settings import (
    AUDIO_OUTPUT_DIR,
    DEFAULT_AUDIO_FORMAT,
    DEFAULT_AUDIO_SAMPLE_RATE,
    DEFAULT_AUDIO_BITRATE,
)


class YouTubeExtractor:
    """Extract audio from YouTube videos."""

    def __init__(
        self,
        output_dir: str = AUDIO_OUTPUT_DIR,
        audio_format: str = DEFAULT_AUDIO_FORMAT,
        sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE,
    ):
        """Initialize the YouTube extractor.

        Args:
            output_dir: Directory to save extracted audio files
            audio_format: Format of the output audio (mp3 or wav)
            sample_rate: Sample rate for the output audio
        """
        self.output_dir = output_dir
        self.audio_format = audio_format.lower()
        self.sample_rate = sample_rate
        
        # Ensure the output directory exists
        os.makedirs(self.output_dir, exist_ok=True)

    def extract_audio(
        self, youtube_url: str, filename: Optional[str] = None
    ) -> Tuple[str, str]:
        """Extract audio from a YouTube video.

        Args:
            youtube_url: URL of the YouTube video
            filename: Optional filename for the output file (without extension)

        Returns:
            tuple: (file_path, video_title)
        """
        try:
            # Create a YouTube object
            yt = pytube.YouTube(youtube_url)
            video_title = yt.title
            
            # If no filename provided, generate a unique one
            if not filename:
                filename = f"{uuid.uuid4()}"
            
            # Get the audio stream
            audio_stream = yt.streams.filter(only_audio=True).first()
            
            # Download the audio
            temp_file = audio_stream.download(
                output_path=self.output_dir,
                filename=f"{filename}.tmp"
            )
            
            # Convert to desired format and sample rate
            audio = AudioSegment.from_file(temp_file)
            
            # Set the sample rate
            if self.sample_rate:
                audio = audio.set_frame_rate(self.sample_rate)
            
            # Set the channels to mono for better STT processing
            audio = audio.set_channels(1)
            
            # Define the output file path
            output_file = os.path.join(
                self.output_dir,
                f"{filename}.{self.audio_format}"
            )
            
            # Export in the desired format
            if self.audio_format == "mp3":
                audio.export(
                    output_file,
                    format="mp3",
                    bitrate=DEFAULT_AUDIO_BITRATE
                )
            elif self.audio_format == "wav":
                audio.export(
                    output_file,
                    format="wav"
                )
            else:
                raise ValueError(f"Unsupported audio format: {self.audio_format}")
            
            # Remove the temporary file
            if os.path.exists(temp_file):
                os.remove(temp_file)
                
            return output_file, video_title
            
        except Exception as e:
            raise Exception(f"Failed to extract audio from YouTube: {str(e)}")

    def get_video_info(self, youtube_url: str) -> dict:
        """Get information about a YouTube video.

        Args:
            youtube_url: URL of the YouTube video

        Returns:
            dict: Video information
        """
        try:
            yt = pytube.YouTube(youtube_url)
            return {
                "title": yt.title,
                "author": yt.author,
                "length_seconds": yt.length,
                "views": yt.views,
                "publish_date": str(yt.publish_date) if yt.publish_date else None,
                "thumbnail_url": yt.thumbnail_url,
            }
        except Exception as e:
            raise Exception(f"Failed to get video info: {str(e)}")