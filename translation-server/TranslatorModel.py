# # translation-server/TranslatorModel.py
# import os
# import torch
# from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
# import logging
# from typing import List, Dict, Union, Iterable
# import time

# logger = logging.getLogger(__name__)
# # 로깅 레벨 설정 (Seldon 환경에서는 자동으로 설정될 수 있음)
# logging.basicConfig(level=logging.INFO)

# # 환경 변수에서 모델 디렉토리 경로 가져오기 (Seldon 배포 시 설정 가능)
# # 또는 Docker 이미지 빌드 시 모델이 복사된 경로 사용
# DEFAULT_MODEL_PATH = "/app/model_files" # /mnt/models 대신 새 경로 사용

# class TranslatorModel(object):
#     """Seldon Core V2 프로토콜을 따르는 일본어-한국어 번역 모델 클래스"""

#     def __init__(self, model_uri: str = None): # model_uri는 Seldon이 전달 가능
#         self.model_path = os.getenv("MODEL_DIR", DEFAULT_MODEL_PATH)
#         self.device = None
#         self.tokenizer = None
#         self.model = None
#         self.loaded = False
#         logger.info(f"Initialized TranslatorModel. Model path set to: {self.model_path}")
#         # __init__에서 바로 로드하거나, load 메소드에서 로드
#         self.load()

#     # TranslatorModel.py -> load() 메소드 수정

#     def load(self):
#         """모델과 토크나이저를 메모리에 로드합니다."""
#         if self.loaded:
#             logger.info("Model already loaded.")
#             return

#         logger.info(f"Attempting to check model path: {self.model_path}")

#         # 1. 경로 존재 확인
#         if not os.path.exists(self.model_path):
#             message = f"Model directory {self.model_path} DOES NOT EXIST."
#             logger.error(message)
#             raise FileNotFoundError(message)
#         else:
#             logger.info(f"Model directory {self.model_path} exists.")

#         # 2. 디렉토리 내용물 확인 (listdir 시도)
#         try:
#             dir_contents = os.listdir(self.model_path)
#             logger.info(f"Successfully listed contents of {self.model_path}: {dir_contents}")
#             # 3. 내용물이 비었는지 확인
#             if not dir_contents:
#                 message = f"Model directory {self.model_path} IS EMPTY."
#                 logger.error(message)
#                 raise FileNotFoundError(message) # 내용물이 없을 때만 오류 발생
#         except OSError as e:
#             # listdir 자체에서 오류 발생 시 (예: 권한 문제)
#             message = f"Cannot list contents of {self.model_path} due to OSError: {e}"
#             logger.error(message, exc_info=True)
#             raise FileNotFoundError(message) from e # 원본 오류 포함하여 다시 발생
#         except Exception as e:
#             # 예상치 못한 다른 오류
#             message = f"Unexpected error checking directory {self.model_path}: {e}"
#             logger.error(message, exc_info=True)
#             raise FileNotFoundError(message) from e

#         # 모든 검사 통과 후 모델 로딩 시도
#         logger.info(f"Directory checks passed. Loading model and tokenizer from {self.model_path}...")
#         try:
#             self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
#             logger.info("Tokenizer loaded successfully.")
#             self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_path)
#             logger.info("Model loaded successfully.")

#             self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
#             self.model.to(self.device)
#             self.model.eval()
#             self.loaded = True
#             logger.info(f"Model moved to device: {self.device} and set to eval mode.")

#         except Exception as e:
#             # 실제 모델/토크나이저 로딩 중 오류 발생 시
#             logger.error(f"Error during model/tokenizer loading from {self.model_path}: {e}", exc_info=True)
#             raise RuntimeError(f"Failed to load model/tokenizer from {self.model_path}") from e

#     def predict(self, X: Union[List[str], str, bytes], names: Iterable[str] = None, meta: Dict = None) -> List[str]:
#         """
#         입력된 일본어 텍스트(들)를 받아 한국어 번역 결과를 반환합니다.
#         Seldon Core V2 REST/gRPC 프로토콜의 입력을 처리합니다.
#         """
#         if not self.loaded:
#              # load()가 실패했거나 호출되지 않은 경우
#              logger.error("Model is not loaded, cannot predict.")
#              raise RuntimeError("Model is not loaded.")

#         start_time = time.time() if 'time' in globals() else None # 시간 측정 (선택적)
#         try:
#             # 입력 데이터 처리 (다양한 입력 형태 처리)
#             if isinstance(X, bytes):
#                 try:
#                     import json
#                     str_data = X.decode('utf-8')
#                     # Seldon V2 Inference Protocol (REST)는 보통 {"inputs": [...]} 형태
#                     # 간단하게 여기서는 JSON 리스트 또는 단일 문자열로 가정
#                     payload = json.loads(str_data)
#                     # V2 protocol에 맞게 입력 추출 (예시, 실제 프로토콜 확인 필요)
#                     # inputs = payload.get("inputs", [])
#                     # input_texts = [item['data'][0] for item in inputs if item['name'] == 'text'] # 예시
#                     # 가장 간단한 가정: 페이로드가 바로 문자열 리스트
#                     if isinstance(payload, list): input_texts = payload
#                     elif isinstance(payload, str): input_texts = [payload]
#                     else: raise ValueError("Invalid JSON payload structure in bytes input")
#                 except Exception as e:
#                     logger.error(f"Failed to parse input bytes as JSON list/string: {e}")
#                     raise ValueError(f"Could not parse input bytes: {e}")
#             elif isinstance(X, str):
#                 input_texts = [X]
#             elif isinstance(X, list) and all(isinstance(item, str) for item in X):
#                 input_texts = X
#             else:
#                 # Seldon V2는 보통 numpy ndarray 등으로 전달할 수도 있음
#                 # 필요시 해당 타입 처리 로직 추가
#                 logger.error(f"Received unexpected input type: {type(X)}")
#                 raise ValueError(f"Unsupported input type: {type(X)}. Expecting str or list[str].")

#             if not input_texts:
#                  logger.warning("Received empty input list for prediction.")
#                  return []

#             logger.info(f"Received {len(input_texts)} text(s) for translation.")
#             logger.debug(f"Input texts: {input_texts}")

#             # 토크나이징
#             inputs = self.tokenizer(input_texts, return_tensors="pt", padding=True, truncation=True, max_length=512).to(self.device)

#             # 번역 생성 (GPU 사용 시 no_grad 필수)
#             with torch.no_grad():
#                 translated_ids = self.model.generate(
#                     **inputs,
#                     max_length=512,
#                     num_beams=4, # 필요시 파라미터 조정
#                     early_stopping=True
#                 )

#             # 디코딩
#             translated_texts = self.tokenizer.batch_decode(translated_ids, skip_special_tokens=True)
#             logger.info(f"Translation successful for {len(translated_texts)} text(s).")
#             logger.debug(f"Translated texts: {translated_texts}")

#             # Seldon Core V2 출력 형식에 맞춰 반환 (간단히 리스트 반환 예시)
#             # 실제로는 {"outputs": [...]} 형태 필요할 수 있음
#             return translated_texts

#         except Exception as e:
#             logger.error(f"Error during prediction: {e}", exc_info=True)
#             raise RuntimeError(f"Prediction failed: {e}") # Seldon에 오류 전파
#         finally:
#              if start_time: logger.info(f"Prediction took {(time.time() - start_time)*1000:.2f} ms")

import os
import torch
from transformers import BertTokenizerFast, GPT2TokenizerFast, EncoderDecoderModel
import logging
from typing import List, Dict, Union, Iterable
import time

logger = logging.getLogger(__name__)
# 로깅 레벨 설정
logging.basicConfig(level=logging.INFO)

# 환경 변수에서 모델 디렉토리 경로 가져오기
DEFAULT_MODEL_PATH = "/app/model_files"

class TranslatorModel(object):
    """Seldon Core V2 프로토콜을 따르는 일본어-한국어 번역 모델 클래스"""

    def __init__(self, model_uri: str = None):
        self.model_path = os.getenv("MODEL_DIR", DEFAULT_MODEL_PATH)
        self.device = None
        self.src_tokenizer = None  # 인코더(일본어) 토크나이저
        self.trg_tokenizer = None  # 디코더(한국어) 토크나이저
        self.model = None
        self.loaded = False
        # 캐시 디렉토리 설정
        os.environ["TRANSFORMERS_CACHE"] = "/tmp/transformers_cache"
        logger.info(f"Initialized TranslatorModel. Model path set to: {self.model_path}")
        # __init__에서 바로 로드
        self.load()

    def load(self):
        """모델과 토크나이저를 메모리에 로드합니다."""
        if self.loaded:
            logger.info("Model already loaded.")
            return

        logger.info(f"Attempting to check model path: {self.model_path}")

        # 1. 경로 존재 확인
        if not os.path.exists(self.model_path):
            message = f"Model directory {self.model_path} DOES NOT EXIST."
            logger.error(message)
            raise FileNotFoundError(message)
        else:
            logger.info(f"Model directory {self.model_path} exists.")

        # 2. 디렉토리 내용물 확인
        try:
            dir_contents = os.listdir(self.model_path)
            logger.info(f"Successfully listed contents of {self.model_path}: {dir_contents}")
            # 3. 내용물이 비었는지 확인
            if not dir_contents:
                message = f"Model directory {self.model_path} IS EMPTY."
                logger.error(message)
                raise FileNotFoundError(message)
                
            # src_tokenizer와 trg_tokenizer 디렉토리 확인
            if 'src_tokenizer' in dir_contents and 'trg_tokenizer' in dir_contents:
                logger.info("Found separate src_tokenizer and trg_tokenizer directories.")
                src_tokenizer_path = os.path.join(self.model_path, 'src_tokenizer')
                trg_tokenizer_path = os.path.join(self.model_path, 'trg_tokenizer')
                
                # 특정 토크나이저 클래스 사용
                try:
                    self.src_tokenizer = BertTokenizerFast.from_pretrained(src_tokenizer_path)
                    logger.info("Source tokenizer (BERT) loaded successfully.")
                    self.trg_tokenizer = GPT2TokenizerFast.from_pretrained(trg_tokenizer_path)
                    logger.info("Target tokenizer (GPT2) loaded successfully.")
                except Exception as e:
                    logger.error(f"Error loading specific tokenizers: {e}", exc_info=True)
                    # 폴백: AutoTokenizer 시도
                    logger.info("Trying AutoTokenizer as fallback...")
                    from transformers import AutoTokenizer
                    self.src_tokenizer = AutoTokenizer.from_pretrained(src_tokenizer_path)
                    self.trg_tokenizer = AutoTokenizer.from_pretrained(trg_tokenizer_path)
                    logger.info("Tokenizers loaded with AutoTokenizer.")
                
                # EncoderDecoderModel 로드
                try:
                    self.model = EncoderDecoderModel.from_pretrained(self.model_path)
                    logger.info("EncoderDecoderModel loaded successfully.")
                except Exception as e:
                    logger.error(f"Error loading EncoderDecoderModel: {e}", exc_info=True)
                    raise RuntimeError(f"Failed to load EncoderDecoderModel from {self.model_path}") from e
            else:
                # 기존 방식 시도 (통합 토크나이저)
                logger.info("No separate tokenizer directories found. Trying standard loading approach.")
                try:
                    from transformers import AutoTokenizer
                    self.src_tokenizer = AutoTokenizer.from_pretrained(self.model_path)
                    self.trg_tokenizer = self.src_tokenizer  # 동일한 토크나이저 사용
                    logger.info("Unified tokenizer loaded successfully.")
                    
                    # Seq2Seq 모델 로드
                    from transformers import AutoModelForSeq2SeqLM
                    self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_path)
                    logger.info("Seq2Seq model loaded successfully.")
                except Exception as e:
                    logger.error(f"Error loading standard model/tokenizer: {e}", exc_info=True)
                    raise RuntimeError(f"Failed to load model/tokenizer from {self.model_path}") from e
                
        except OSError as e:
            message = f"Cannot list contents of {self.model_path} due to OSError: {e}"
            logger.error(message, exc_info=True)
            raise FileNotFoundError(message) from e
        except Exception as e:
            message = f"Unexpected error checking directory {self.model_path}: {e}"
            logger.error(message, exc_info=True)
            raise FileNotFoundError(message) from e

        # 디바이스 설정 및 모델 로드 완료
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.model.eval()
        self.loaded = True
        logger.info(f"Model moved to device: {self.device} and set to eval mode.")

    def predict(self, X: Union[List[str], str, bytes, 'numpy.ndarray'], names: Iterable[str] = None, meta: Dict = None) -> List[str]:
        """입력된 일본어 텍스트(들)를 받아 한국어 번역 결과를 반환합니다."""
        if not self.loaded:
            logger.error("Model is not loaded, cannot predict.")
            raise RuntimeError("Model is not loaded.")

        start_time = time.time()
        try:
            # 입력 데이터 처리
            if isinstance(X, bytes):
                try:
                    import json
                    str_data = X.decode('utf-8')
                    payload = json.loads(str_data)
                    if isinstance(payload, list): input_texts = payload
                    elif isinstance(payload, str): input_texts = [payload]
                    else: raise ValueError("Invalid JSON payload structure in bytes input")
                except Exception as e:
                    logger.error(f"Failed to parse input bytes as JSON list/string: {e}")
                    raise ValueError(f"Could not parse input bytes: {e}")
            elif str(type(X)) == "<class 'numpy.ndarray'>":  # numpy 모듈 없이도 작동하도록 문자열 비교
                # numpy 배열을 파이썬 리스트로 변환
                input_list = X.tolist()
                # 중첩 배열 처리 (Seldon Core v1.0 API 형식)
                if input_list and isinstance(input_list[0], list):
                    input_list = input_list[0]
                
                # 각 항목이 문자열인지 확인
                input_texts = []
                for item in input_list:
                    if isinstance(item, str):
                        input_texts.append(item)
                    else:
                        # 숫자나 다른 타입을 문자열로 변환
                        input_texts.append(str(item))
                
                logger.info(f"Converted numpy.ndarray to list of {len(input_texts)} strings")
            elif isinstance(X, str):
                input_texts = [X]
            elif isinstance(X, list):
                # 리스트의 각 항목이 문자열인지 확인하고 필요시 변환
                input_texts = [str(item) if not isinstance(item, str) else item for item in X]
            else:
                logger.error(f"Received unexpected input type: {type(X)}")
                raise ValueError(f"Unsupported input type: {type(X)}. Expecting str or list[str].")

            if not input_texts:
                logger.warning("Received empty input list for prediction.")
                return []

            logger.info(f"Received {len(input_texts)} text(s) for translation.")
            logger.debug(f"Input texts: {input_texts}")

            # 인코더-디코더 모델 사용 방식으로 수정
            # 소스 토크나이저로 인코딩
            inputs = self.src_tokenizer(input_texts, return_tensors="pt", padding=True, truncation=True, max_length=512).to(self.device)

            # 번역 생성
            with torch.no_grad():
                translated_ids = self.model.generate(
                    **inputs,
                    max_length=512,
                    num_beams=4,
                    early_stopping=True
                )

            # 타겟 토크나이저로 디코딩 (src_tokenizer와 trg_tokenizer가 같으면 동일하게 작동)
            translated_texts = self.trg_tokenizer.batch_decode(translated_ids, skip_special_tokens=True)
            logger.info(f"Translation successful for {len(translated_texts)} text(s).")
            logger.debug(f"Translated texts: {translated_texts}")

            return translated_texts

        except Exception as e:
            logger.error(f"Error during prediction: {e}", exc_info=True)
            raise RuntimeError(f"Prediction failed: {e}")
        finally:
            logger.info(f"Prediction took {(time.time() - start_time)*1000:.2f} ms")