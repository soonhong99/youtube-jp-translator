# import io
# import os
# from fastapi import FastAPI, HTTPException, Body
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.responses import StreamingResponse

# # 분리된 tts 모듈 import
# from src.tts import synthesize_and_save

# app = FastAPI(
#     title="Japanese-only TTS Synthesizer",
#     description="Coqui TTS의 일본어 Tacotron2 + HiFi-GAN 모델로 텍스트→음성 변환",
#     version="1.0.0"
# )

# # CORS 설정
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],      # 운영 시에는 실제 도메인만 허용하도록 변경
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# @app.post("/tts", summary="일본어 텍스트를 wav 스트림으로 반환")
# async def synthesize_tts(text: str = Body(..., embed=True)):
#     """
#     요청 예시:
#     {
#       "text": "こんにちは、世界！"
#     }
#     - synthesize_and_save() 호출 후, WAV 바이트를 StreamingResponse로 반환.
#     """
#     if not text:
#         raise HTTPException(status_code=400, detail="text 필드를 비워둘 수 없습니다.")
#     try:
#         wav_bytes = synthesize_and_save(text)        # tts.py의 함수 호출
#         return StreamingResponse(
#             io.BytesIO(wav_bytes),
#             media_type="audio/wav"
#         )
#     except Exception as ex:
#         raise HTTPException(status_code=500, detail=f"TTS 합성 중 오류: {ex}")

# backend/services/tts-synthesizer/src/main.py

import os
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from src.tts import synthesize_and_save

app = FastAPI(
    title="Japanese-only TTS Synthesizer",
    description="Coqui TTS의 일본어 전용 모델(tts_models/ja/kokoro/tacotron2-DDC) + HiFi-GAN vocoder",
    version="1.0.0"
)

# CORS 설정 (테스트 단계에서는 모든 출처 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Body를 명확히 받기 위한 Pydantic 모델 정의
class TextRequest(BaseModel):
    text: str

# @app.post("/tts", summary="일본어 텍스트를 wav 스트림으로 반환")
# async def synthesize_tts(req: TextRequest):
#     print("=== 받은 req 값:", req)
#     text = req.text
#     if not text:
#         raise HTTPException(status_code=400, detail="text 필드를 비워둘 수 없습니다.")
#     try:
#         buffer = synthesize_and_save(text)
#         return StreamingResponse(buffer, media_type="audio/wav")
#     except Exception as ex:
#         raise HTTPException(status_code=500, detail=f"TTS 합성 중 오류: {ex}")

@app.post("/tts", summary="일본어 텍스트를 wav 스트림으로 반환")
async def synthesize_tts(req: dict = Body(...)):
    print("=== 받은 req 값:", req)
    text = req.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="text 필드를 비워둘 수 없습니다.")
    try:
        buffer = synthesize_and_save(text)
        return StreamingResponse(buffer, media_type="audio/wav")
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"TTS 합성 중 오류: {ex}")
