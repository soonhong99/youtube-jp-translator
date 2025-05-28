from fastapi import FastAPI
from pydantic import BaseModel
from src.tts import synthesize_and_save

app = FastAPI()

class TTSRequest(BaseModel):
    text: str

@app.post("/synthesize_audio")
def synthesize(request: TTSRequest):
    output_path = synthesize_and_save(request.text)
    return {"audio_path": output_path}