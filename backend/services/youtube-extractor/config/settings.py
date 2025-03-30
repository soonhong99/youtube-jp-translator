# config/settings.py

import os

# YouTube extractor settings
AUDIO_OUTPUT_DIR = os.environ.get("AUDIO_OUTPUT_DIR", "/tmp/youtube_audio")
DEFAULT_AUDIO_FORMAT = os.environ.get("DEFAULT_AUDIO_FORMAT", "wav")  # or "mp3"
DEFAULT_AUDIO_BITRATE = os.environ.get("DEFAULT_AUDIO_BITRATE", "128k")
DEFAULT_AUDIO_SAMPLE_RATE = int(os.environ.get("DEFAULT_AUDIO_SAMPLE_RATE", "16000"))

# Ensure output directory exists
os.makedirs(AUDIO_OUTPUT_DIR, exist_ok=True)