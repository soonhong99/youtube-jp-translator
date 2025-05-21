import asyncio
import json
import logging
import threading
import time # For sleep in consumer retry loop

from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import KafkaError, NoBrokersAvailable

from .config import (
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_TRANSLATION_REQUESTS_TOPIC,
    KAFKA_TRANSLATION_RESULTS_TOPIC,
    KAFKA_TRANSLATION_WORKER_GROUP_ID,
    logger
)

producer = None

def get_kafka_producer():
    global producer
    if producer is None:
        while True:
            try:
                producer = KafkaProducer(
                    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                    key_serializer=lambda k: k.encode('utf-8') if k else None,
                    retries=5,  # Retry up to 5 times
                    retry_backoff_ms=1000  # Wait 1 second between retries
                )
                logger.info("KafkaProducer initialized successfully.")
                return producer
            except NoBrokersAvailable:
                logger.error(f"Kafka brokers at {KAFKA_BOOTSTRAP_SERVERS} not available. Retrying in 5 seconds...")
                time.sleep(5)
            except Exception as e:
                logger.error(f"Failed to initialize KafkaProducer: {e}", exc_info=True)
                time.sleep(5) # General retry for other unexpected errors
    return producer


def send_translation_result(task_id: str, korean_text: str | None, error_message: str | None):
    kafka_producer = get_kafka_producer()
    if not kafka_producer:
        logger.error(f"[Task ID: {task_id}] Kafka producer not available. Cannot send translation result.")
        # Potentially raise an error or handle more gracefully if this is critical path
        return

    status = "TRANSLATED" if korean_text else "TRANSLATION_ERROR"
    
    message = {
        "task_id": task_id,
        "korean_text": korean_text,
        "status": status,
        "error_message": error_message,
        "service_name": "translation-service" # Optional: for easier debugging/tracing
    }
    
    try:
        logger.info(f"[Task ID: {task_id}] Sending translation result to Kafka topic '{KAFKA_TRANSLATION_RESULTS_TOPIC}'. Status: {status}")
        future = kafka_producer.send(KAFKA_TRANSLATION_RESULTS_TOPIC, key=task_id, value=message)
        # Optional: Block for synchronous send or add callbacks for async error handling
        # record_metadata = future.get(timeout=10)
        # logger.debug(f"Message sent to topic {record_metadata.topic} partition {record_metadata.partition} offset {record_metadata.offset}")
    except KafkaError as e:
        logger.error(f"[Task ID: {task_id}] Failed to send message to Kafka: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] An unexpected error occurred while sending message to Kafka: {e}", exc_info=True)


class KafkaConsumerThread(threading.Thread):
    def __init__(self, loop, process_message_callback_async, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.daemon = True  # Ensure thread exits when main program exits
        self._loop = loop
        self._process_message_callback_async = process_message_callback_async
        self._consumer = None
        self._stop_event = threading.Event()

    def _initialize_consumer(self):
        while not self._stop_event.is_set():
            try:
                self._consumer = KafkaConsumer(
                    KAFKA_TRANSLATION_REQUESTS_TOPIC,
                    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                    auto_offset_reset='earliest', # Or 'latest' depending on desired behavior
                    group_id=KAFKA_TRANSLATION_WORKER_GROUP_ID,
                    value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                    key_deserializer=lambda k: k.decode('utf-8') if k else None,
                    # Enable auto commit, or manage commits manually for more control
                    enable_auto_commit=True, 
                    auto_commit_interval_ms=5000 # e.g., commit every 5 seconds
                )
                logger.info(f"KafkaConsumer connected to {KAFKA_BOOTSTRAP_SERVERS} for topic '{KAFKA_TRANSLATION_REQUESTS_TOPIC}' with group ID '{KAFKA_TRANSLATION_WORKER_GROUP_ID}'.")
                return True
            except NoBrokersAvailable:
                logger.error(f"Kafka brokers at {KAFKA_BOOTSTRAP_SERVERS} not available for consumer. Retrying in 10 seconds...")
                time.sleep(10)
            except Exception as e:
                logger.error(f"Failed to initialize KafkaConsumer: {e}. Retrying in 10 seconds...", exc_info=True)
                time.sleep(10)
        return False

    def run(self):
        if not self._initialize_consumer():
            logger.error("Consumer initialization failed after multiple retries. Thread exiting.")
            return

        logger.info("KafkaConsumer thread started. Waiting for messages...")
        try:
            while not self._stop_event.is_set():
                if not self._consumer: # Should be initialized, but as a safeguard
                    logger.error("Consumer is None, attempting re-initialization...")
                    if not self._initialize_consumer():
                        logger.error("Re-initialization failed. Thread exiting.")
                        break
                    
                # Poll for messages. Timeout can be adjusted.
                # Using a small timeout to allow the stop_event to be checked periodically.
                messages = self._consumer.poll(timeout_ms=1000, max_records=1) 
                if not messages:
                    continue

                for topic_partition, msg_list in messages.items():
                    for msg in msg_list:
                        logger.info(f"Received message: Topic={msg.topic}, Partition={msg.partition}, Offset={msg.offset}, Key={msg.key}")
                        logger.debug(f"Message value: {msg.value}")
                        try:
                            # Schedule the async callback in the provided event loop
                            asyncio.run_coroutine_threadsafe(
                                self._process_message_callback_async(msg.value), 
                                self._loop
                            )
                        except Exception as e:
                            logger.error(f"Error processing message or scheduling callback: {e}", exc_info=True)
                            # Consider how to handle messages that fail to process:
                            # - Log and move on (current behavior with auto-commit)
                            # - Implement a dead-letter queue
                            # - Stop the consumer (if critical)
        except Exception as e:
            logger.error(f"Unhandled exception in KafkaConsumerThread run loop: {e}", exc_info=True)
        finally:
            if self._consumer:
                logger.info("Closing Kafka consumer.")
                self._consumer.close()
            logger.info("KafkaConsumerThread has stopped.")

    def stop(self):
        logger.info("Stopping KafkaConsumerThread...")
        self._stop_event.set()
        # The consumer.poll timeout will ensure the loop eventually exits.
        # If consumer.close() is blocking, consider not waiting for join or a timeout.
        # self.join() # Optionally wait for the thread to finish

# Global consumer thread instance
consumer_thread = None

def start_kafka_consumer(loop, process_message_callback_async):
    global consumer_thread
    if consumer_thread is None or not consumer_thread.is_alive():
        logger.info("Initializing and starting Kafka consumer thread...")
        consumer_thread = KafkaConsumerThread(loop, process_message_callback_async)
        consumer_thread.start()
    else:
        logger.info("Kafka consumer thread is already running.")

def stop_kafka_consumer():
    global consumer_thread
    if consumer_thread and consumer_thread.is_alive():
        logger.info("Signaling Kafka consumer thread to stop...")
        consumer_thread.stop()
        consumer_thread.join(timeout=10) # Wait for thread to stop
        if consumer_thread.is_alive():
            logger.warning("Kafka consumer thread did not stop in time.")
        consumer_thread = None
    else:
        logger.info("Kafka consumer thread is not running or already stopped.")

# Example of an async callback function (would typically be in main.py)
# async def example_process_message(message_data):
#     logger.info(f"Async processing message: {message_data}")
#     await asyncio.sleep(1) # Simulate async work
#     logger.info("Async processing complete.")

if __name__ == "__main__":
    # This is for basic testing of Kafka client setup.
    # Requires Kafka to be running and .env or environment variables to be set.
    from dotenv import load_dotenv
    import os
    dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    load_dotenv(dotenv_path=dotenv_path)
    
    # Re-initialize logger for standalone run if necessary
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "DEBUG").upper())
    
    # Update config variables if not already loaded by import
    KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092") # Default to localhost for local test
    KAFKA_TRANSLATION_REQUESTS_TOPIC = os.getenv("KAFKA_TRANSLATION_REQUESTS_TOPIC", "translation_requests_test")
    KAFKA_TRANSLATION_RESULTS_TOPIC = os.getenv("KAFKA_TRANSLATION_RESULTS_TOPIC", "translation_results_test")
    KAFKA_TRANSLATION_WORKER_GROUP_ID = os.getenv("KAFKA_TRANSLATION_WORKER_GROUP_ID", "test_workers_group")

    logger.info("Starting Kafka client test...")

    # Test producer
    producer_instance = get_kafka_producer()
    if producer_instance:
        logger.info("Producer obtained. Sending test message...")
        send_translation_result("test_task_001", "테스트 한국어 텍스트입니다.", None)
        send_translation_result("test_task_002", None, "테스트 에러 메시지입니다.")
        logger.info("Test messages sent.")
    else:
        logger.error("Failed to obtain producer for testing.")

    # Test consumer (requires an event loop)
    # async def sample_processor(message):
    #     logger.info(f"Test Consumer Received: {message}")
    #     await asyncio.sleep(0.1)

    # loop = asyncio.get_event_loop()
    # start_kafka_consumer(loop, sample_processor)
    
    # try:
    #     logger.info("Consumer test running for 20 seconds... Send messages to 'translation_requests_test' topic.")
    #     time.sleep(20) # Keep main thread alive for consumer to run
    # except KeyboardInterrupt:
    #     logger.info("Keyboard interrupt received.")
    # finally:
    #     logger.info("Stopping consumer test...")
    #     stop_kafka_consumer()
    #     logger.info("Consumer test finished.")

    # Note: Running asyncio loop and consumer thread properly for testing here can be complex.
    # The main application in main.py will handle the loop management.
    logger.info("Kafka client test script finished. For consumer testing, run via main.py or a more dedicated test setup.")
