import os
from dotenv import load_dotenv
import logging

# Load environment variables from .env file if it exists
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TRANSLATION_REQUESTS_TOPIC = os.getenv("KAFKA_TRANSLATION_REQUESTS_TOPIC", "translation_requests")
KAFKA_TRANSLATION_RESULTS_TOPIC = os.getenv("KAFKA_TRANSLATION_RESULTS_TOPIC", "translation_results")
KAFKA_TRANSLATION_WORKER_GROUP_ID = os.getenv("KAFKA_TRANSLATION_WORKER_GROUP_ID", "translation_workers_group")

TRANSLATION_PROMPT_TEMPLATE = os.getenv(
    "TRANSLATION_PROMPT_TEMPLATE",
    "당신은 일본어 구어체와 한국어 일상 대화 번역에 매우 능숙한 전문 번역가입니다. "
    "입력되는 일본어는 유튜브 영상, 일상 대화 등에서 발췌된 구어체입니다. "
    "번역 결과는 한국어 사용자가 실제 대화에서 사용할 법한 자연스러운 말투여야 하며, "
    "문어체가 아닌 구어체 어투를 유지해야 합니다. "
    "주어진 일본어 텍스트를 매우 자연스러운 한국어 일상 대화체로 번역해 주세요. "
    "원문의 의미와 어투, 뉘앙스를 최대한 살리면서, "
    "한국인이 듣기에 전혀 어색하지 않은 결과물을 만들어 주세요. "
    "다음은 번역할 텍스트입니다: {JAPANESE_TEXT_PLACEHOLDER}"
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Basic logging configuration
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY is not set. Translation functionality will not work.")

# You can add more specific validation for other critical variables if needed
if KAFKA_BOOTSTRAP_SERVERS == "kafka:9092":
    logger.info(f"Using default KAFKA_BOOTSTRAP_SERVERS: {KAFKA_BOOTSTRAP_SERVERS}")

logger.info("Configuration loaded.")
logger.info(f"Translation prompt template: {TRANSLATION_PROMPT_TEMPLATE[:100]}...") # Log a snippet
logger.info(f"Kafka request topic: {KAFKA_TRANSLATION_REQUESTS_TOPIC}")
logger.info(f"Kafka result topic: {KAFKA_TRANSLATION_RESULTS_TOPIC}")
logger.info(f"Kafka group ID: {KAFKA_TRANSLATION_WORKER_GROUP_ID}")
