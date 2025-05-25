# 별도 스크립트나 Colab 등에서 실행
from huggingface_hub import snapshot_download

model_name = "sappho192/aihub-ja-ko-translator"
local_model_dir = "./models/aihub-ja-ko-translator"

snapshot_download(repo_id=model_name, local_dir=local_model_dir)
print(f"Model '{model_name}' downloaded to {local_model_dir}")