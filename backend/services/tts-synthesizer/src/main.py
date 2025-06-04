from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from TTS.api import TTS
import uuid
import os

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 또는 ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

tts = TTS("tts_models/ja/kokoro/tacotron2-DDC")
AUDIO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../audio"))
os.makedirs(AUDIO_DIR, exist_ok=True)

class TTSRequest(BaseModel):
    text: str

@app.post("/synthesize_tts")
async def synthesize_tts(body: TTSRequest):
    text = body.text
    audio_id = str(uuid.uuid4())
    file_path = os.path.join(AUDIO_DIR, f"{audio_id}.wav")
    tts.tts_to_file(text=text, file_path=file_path)
    return JSONResponse({"audio_url": f"/audio/{audio_id}.wav"})

@app.get("/audio/{audio_file}")
async def get_audio(audio_file: str):
    file_path = os.path.join(AUDIO_DIR, audio_file)
    if not os.path.exists(file_path):
        return JSONResponse({"error": "File not found"}, status_code=404)
    return FileResponse(file_path, media_type="audio/wav")
