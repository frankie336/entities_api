import re
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, StoppingCriteria, StoppingCriteriaList, logging
import time

from config.model_paths import get_model_path

# Suppress informational logging from transformers.
logging.set_verbosity_error()


def process_think_tokens(text: str) -> str:
    """
    Removes any content between <think> and </think> (inclusive), except that if the text begins with "<think>\n",
    that prefix is preserved.
    """
    if text.startswith("<think>"):
        prefix = "<think>\n"
        rest = text[len("<think>"):]
        rest = re.sub(r"<think>.*?</think>", "", rest, flags=re.DOTALL)
        return prefix + rest.strip()
    else:
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


class StreamStoppingCriteria(StoppingCriteria):
    def __init__(self, stop_token_id):
        self.stop_token_id = stop_token_id

    def __call__(self, input_ids, scores, **kwargs):
        # Stop generation if the last token equals the EOS token.
        return input_ids[0, -1] == self.stop_token_id


class InferenceService:
    def __init__(self, model_name: str = "ri-qwen2.5-math-1.5b", use_docker=True):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.use_docker = use_docker
        self.model_path = get_model_path(model_name, use_docker=self.use_docker)

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        print(f"Loading model from: {self.model_path}")

        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32
        ).to(self.device)
        self.model.eval()

    def _format_messages(self, messages: list) -> str:
        # Simply join messages with newlines.
        # All instructions should be contained in the user prompt.
        # (For mathematical problems, include a directive such as:
        #  "Please reason step by step, and put your final answer within \\boxed{}." in the user prompt.)
        formatted = "\n".join(f"{msg['role'].capitalize()}: {msg['content']}" for msg in messages)
        return formatted + "\nassistant:"

    def generate_text(self, messages: list, max_length: int = 200, temperature: float = 0.6) -> str:
        """
        Non-streamed generation.
        Generates a full response (with default temperature 0.6) and removes any stray <think> tokens.
        Also, enforces that the final answer begins with "<think>\n".
        """
        prompt = self._format_messages(messages)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_length=max_length,
                temperature=temperature,
                pad_token_id=self.tokenizer.eos_token_id,
                return_legacy_cache=True
            )
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        final_response = process_think_tokens(response[len(prompt):].strip())
        if not final_response.startswith("<think>"):
            final_response = "<think>\n" + final_response
        return final_response

    def stream_response(self, messages: list, max_length: int = 200, temperature: float = 0.6,
                        show_speed: bool = True) -> str:
        """
        Streams raw text tokens (after filtering out <think> tokens) as they are generated.
        A space is inserted before a token if:
          - There is already generated text, and
          - The new token does not start with whitespace or with punctuation (e.g. .,!,?).

        Additionally, we enforce that the response begins with "<think>\n". If the first token from the model
        does not provide this, we prepend it.

        This design streams raw tokens; the client is expected to accumulate them and perform markdown parsing
        and further formatting if needed.
        """
        prompt = self._format_messages(messages)
        # Start with initial input_ids from the prompt.
        input_ids = self.tokenizer(prompt, return_tensors="pt").to(self.device).input_ids
        stopping_criteria = StoppingCriteriaList([StreamStoppingCriteria(self.tokenizer.eos_token_id)])
        start_time = time.time()
        tokens_received = 0
        generated_text = ""
        first_token_emitted = False

        for _ in range(max_length):
            with torch.no_grad():
                outputs = self.model.generate(
                    input_ids,
                    max_new_tokens=1,
                    temperature=temperature,
                    pad_token_id=self.tokenizer.eos_token_id,
                    stopping_criteria=stopping_criteria,
                    return_dict_in_generate=True,
                    output_scores=True,
                    return_legacy_cache=True
                )
            # Get only the newly generated token.
            new_token = outputs.sequences[:, -1:]
            if new_token.item() == self.tokenizer.eos_token_id:
                break
            decoded_token = self.tokenizer.decode(new_token[0], skip_special_tokens=False)
            decoded_token = process_think_tokens(decoded_token.rstrip("\n"))
            # Insert a space if needed.
            if generated_text and decoded_token and not decoded_token[0].isspace() and decoded_token[0] not in ('.', ',', '!', '?'):
                decoded_token = " " + decoded_token
            # On the very first token, enforce "<think>\n" if not already present.
            if not first_token_emitted:
                if not decoded_token.startswith("<think>"):
                    yield "<think>\n"
                    generated_text += "<think>\n"
                    tokens_received += 1
                first_token_emitted = True
            yield decoded_token
            generated_text += decoded_token
            tokens_received += 1
            # Update input_ids by concatenating the new token.
            input_ids = torch.cat([input_ids, new_token], dim=1)
        elapsed_time = time.time() - start_time
        if elapsed_time > 0 and show_speed:
            print(f"\nTotal tokens per second: {tokens_received / elapsed_time:.2f}")
        print()

if __name__ == "__main__":
    service = InferenceService(use_docker=False)
    messages = [
        {"role": "user", "content": "Show me an example of a Python function. Please reason step by step, and put your final answer within \\boxed{}."}
    ]
    # Uncomment below to test non-streamed response.
    # print("\n=== Non-Streaming Response ===")
    # full_response = service.generate_text(messages, max_length=600, temperature=0.6)
    # print("Assistant:", full_response)
    print("\n=== Streaming Response ===")
    print("Assistant: ", end="", flush=True)
    for token in service.stream_response(messages, max_length=3000, temperature=0.6, show_speed=True):
        print(token, end="", flush=True)
    print()
