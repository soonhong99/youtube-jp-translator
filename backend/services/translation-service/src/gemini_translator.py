import google.generativeai as genai
import logging
from .config import GEMINI_API_KEY, TRANSLATION_PROMPT_TEMPLATE, logger

class GeminiTranslator:
    def __init__(self):
        if not GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY is not configured. Translation will fail.")
            raise ValueError("GEMINI_API_KEY is not set.")
        
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            # Model selection can be made configurable if needed
            self.model = genai.GenerativeModel('gemini-pro')
            logger.info("Gemini API client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini API client: {e}", exc_info=True)
            raise

    def translate(self, japanese_text: str, task_id: str = "N/A") -> tuple[str | None, str | None]:
        """
        Translates Japanese text to Korean using the Gemini API.

        Args:
            japanese_text: The Japanese text to translate.
            task_id: The ID of the task for logging purposes.

        Returns:
            A tuple containing (korean_text, error_message).
            If successful, korean_text is the translated text, and error_message is None.
            If failed, korean_text is None, and error_message contains the error description.
        """
        if not japanese_text:
            logger.warning(f"[Task ID: {task_id}] Empty Japanese text provided for translation.")
            return None, "Input Japanese text was empty."

        try:
            prompt = TRANSLATION_PROMPT_TEMPLATE.format(JAPANESE_TEXT_PLACEHOLDER=japanese_text)
            logger.debug(f"[Task ID: {task_id}] Sending prompt to Gemini: {prompt[:200]}...") # Log snippet

            # GenerationConfig can be added for more control (temperature, top_p, etc.)
            # config = genai.types.GenerationConfig(candidate_count=1, temperature=0.5)
            # response = self.model.generate_content(prompt, generation_config=config)
            
            response = self.model.generate_content(prompt)

            if response.parts:
                korean_text = "".join(part.text for part in response.parts)
                logger.info(f"[Task ID: {task_id}] Successfully translated text. Snippet: {korean_text[:100]}...")
                # Check for safety ratings or block reasons if necessary
                if response.prompt_feedback and response.prompt_feedback.block_reason:
                    logger.warning(f"[Task ID: {task_id}] Translation may have been affected by safety settings. Reason: {response.prompt_feedback.block_reason}")
                    return None, f"Content blocked by safety settings: {response.prompt_feedback.block_reason}"
                return korean_text, None
            elif response.prompt_feedback and response.prompt_feedback.block_reason:
                logger.error(f"[Task ID: {task_id}] Prompt blocked by Gemini API. Reason: {response.prompt_feedback.block_reason}")
                return None, f"Prompt blocked by safety policy: {response.prompt_feedback.block_reason}"
            else:
                logger.warning(f"[Task ID: {task_id}] Gemini API returned an empty response or no text part. Full response: {response}")
                return None, "Gemini API returned an empty response."

        except Exception as e:
            logger.error(f"[Task ID: {task_id}] Error calling Gemini API: {e}", exc_info=True)
            # More specific error handling for google.api_core.exceptions can be added
            # For example, to catch google.api_core.exceptions.ResourceExhausted for rate limits
            return None, f"Gemini API call failed: {str(e)}"

# Example usage (for testing purposes, not part of the main flow)
if __name__ == "__main__":
    # This requires .env to be in the same directory or parent for local testing
    # or GEMINI_API_KEY to be set in the environment.
    # Ensure config.py loads .env correctly if you run this directly.
    from dotenv import load_dotenv
    import os
    # Assuming this script is in src, .env is in parent 'translation-service'
    dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    load_dotenv(dotenv_path=dotenv_path)
    
    # Re-initialize logger for standalone run if necessary
    logging.basicConfig(level=logging.INFO)
    
    # Update config variables if not already loaded by import
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    TRANSLATION_PROMPT_TEMPLATE = os.getenv(
        "TRANSLATION_PROMPT_TEMPLATE",
        "Translate from Japanese to Korean: {JAPANESE_TEXT_PLACEHOLDER}" # Simplified for test
    )

    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not found. Please set it in .env or environment.")
    else:
        translator = GeminiTranslator()
        test_text = "こんにちは、元気ですか？" # "Hello, how are you?"
        print(f"Translating: {test_text}")
        korean, error = translator.translate(test_text, task_id="test_01")
        if error:
            print(f"Translation Error: {error}")
        else:
            print(f"Korean Translation: {korean}")

        test_text_empty = ""
        print(f"Translating empty text: '{test_text_empty}'")
        korean, error = translator.translate(test_text_empty, task_id="test_02")
        if error:
            print(f"Translation Error (empty): {error}")
        else:
            print(f"Korean Translation (empty): {korean}")

        # Test with a potentially problematic prompt (if safety settings are strict)
        # This is just a placeholder, actual safety triggers are complex
        test_text_problematic = "これは不適切なコンテンツかもしれません。" 
        print(f"Translating potentially problematic text: {test_text_problematic}")
        korean, error = translator.translate(test_text_problematic, task_id="test_03")
        if error:
            print(f"Translation Error (problematic): {error}")
        else:
            print(f"Korean Translation (problematic): {korean}")
