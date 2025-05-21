import asyncio
import logging
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager

from .config import logger, GEMINI_API_KEY # Ensure logger is configured early
from .gemini_translator import GeminiTranslator
from .kafka_client import (
    get_kafka_producer,
    send_translation_result,
    start_kafka_consumer,
    stop_kafka_consumer,
)

# Global variables for shared instances
translator_instance: GeminiTranslator | None = None

async def process_translation_request(message_data: dict):
    """
    Processes a translation request received from Kafka.
    """
    task_id = message_data.get("task_id")
    japanese_text = message_data.get("japanese_text") # Or "text_to_translate" etc.
    # language = message_data.get("language") # If supporting multiple source languages in future

    if not task_id or not japanese_text:
        logger.error(f"Missing task_id or japanese_text in Kafka message: {message_data}")
        # Optionally send an error message back to Kafka if a task_id is present
        if task_id:
            send_translation_result(task_id, None, "Missing japanese_text in request.")
        return

    logger.info(f"[Task ID: {task_id}] Received translation request for Japanese text: '{japanese_text[:100]}...'")

    if not translator_instance:
        logger.error(f"[Task ID: {task_id}] Translator instance is not available.")
        send_translation_result(task_id, None, "Translator service not initialized.")
        return

    try:
        korean_text, error_message = await asyncio.to_thread(
            translator_instance.translate, 
            japanese_text, 
            task_id
        )
        
        if error_message:
            logger.error(f"[Task ID: {task_id}] Translation failed: {error_message}")
            send_translation_result(task_id, None, error_message)
        else:
            logger.info(f"[Task ID: {task_id}] Translation successful. Sending result to Kafka.")
            send_translation_result(task_id, korean_text, None)
            
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Unhandled exception during translation processing: {e}", exc_info=True)
        send_translation_result(task_id, None, f"An unexpected error occurred: {str(e)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global translator_instance
    logger.info("Translation service starting up...")

    # Initialize Gemini Translator
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY is not set. Proceeding without translation capability for now.")
        # Depending on strictness, you might choose to raise an exception or prevent startup
        # For now, we allow it to start but translation will fail.
    else:
        try:
            translator_instance = GeminiTranslator()
            logger.info("GeminiTranslator initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize GeminiTranslator: {e}. Service will not function correctly.", exc_info=True)
            # Optionally, re-raise to prevent startup if translator is critical
            # raise

    # Initialize Kafka Producer
    try:
        get_kafka_producer() # This initializes the producer
        logger.info("KafkaProducer connection attempt initiated.")
    except Exception as e:
        logger.error(f"Failed to initialize KafkaProducer: {e}. Results cannot be sent.", exc_info=True)
        # Optionally, re-raise

    # Start Kafka Consumer
    # The consumer needs an event loop to run its async callbacks.
    # FastAPI's main event loop can be used.
    loop = asyncio.get_event_loop()
    try:
        start_kafka_consumer(loop, process_translation_request)
        logger.info("KafkaConsumer thread started.")
    except Exception as e:
        logger.error(f"Failed to start Kafka consumer: {e}", exc_info=True)
        # Optionally, re-raise

    yield

    logger.info("Translation service shutting down...")
    # Cleanup resources
    stop_kafka_consumer()
    
    # Kafka producer connection is typically closed on garbage collection or explicitly if needed
    # producer = get_kafka_producer()
    # if producer:
    #     producer.close()
    # logger.info("Kafka producer closed.")

app = FastAPI(
    title="Translation Service",
    description="Consumes Japanese text from Kafka, translates it to Korean using Gemini, and sends results back to Kafka.",
    lifespan=lifespan
)

@app.get("/health", summary="Health Check", tags=["Monitoring"])
async def health_check():
    """
    Provides a basic health check endpoint.
    Checks if Kafka producer is initialized (basic check).
    More checks can be added (e.g., Gemini API status if a test call is feasible).
    """
    # Basic check: is producer available?
    # Note: This doesn't guarantee Kafka is fully operational, just that init was attempted.
    kafka_ok = get_kafka_producer() is not None
    translator_ok = translator_instance is not None if GEMINI_API_KEY else True # If no key, consider it "ok" for startup
    
    if kafka_ok and translator_ok:
        return {"status": "healthy", "kafka_producer_initialized": kafka_ok, "translator_initialized": translator_ok}
    else:
        raise HTTPException(
            status_code=503, 
            detail={
                "status": "unhealthy", 
                "kafka_producer_initialized": kafka_ok,
                "translator_initialized": translator_ok,
                "message": "One or more components failed to initialize. Check logs."
            }
        )

# To run this app (assuming uvicorn is installed):
# uvicorn backend.services.translation-service.src.main:app --reload --port 8002 (example port)
# Ensure PYTHONPATH includes the project root if running from outside the 'src' directory.
# Example: PYTHONPATH=. uvicorn src.main:app --host 0.0.0.0 --port 80
# (as defined in Dockerfile CMD)

if __name__ == "__main__":
    # This block is for local development and debugging, not for production.
    # Production will use the uvicorn command specified in Dockerfile.
    import uvicorn
    logger.info("Running Uvicorn locally for development...")
    # For local dev, ensure .env is in translation-service directory or environment variables are set
    # from dotenv import load_dotenv
    # load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))
    
    # You might need to adjust host and port for local testing
    uvicorn.run(app, host="0.0.0.0", port=8003, log_level="info") # Example port for local run
    # The lifespan events will handle Kafka consumer start/stop.
```
