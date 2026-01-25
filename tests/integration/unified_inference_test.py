"""
Automated Model Benchmark: Reasoning & Tool Use
-----------------------------------------------
1. Loops through models across DIFFERENT PROVIDERS.
2. Streams output visually to console.
3. Updates a persistent Markdown report with Endpoint IDs.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from constants import TOGETHER_AI_MODELS
from dotenv import load_dotenv
from projectdavid import Entity

# ------------------------------------------------------------------
# 0. Setup & Config
# ------------------------------------------------------------------
root_dir = Path(__file__).resolve().parents[2]
load_dotenv()

# ANSI Colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

# Global Config
BASE_URL = os.getenv("BASE_URL", "http://localhost:9000")
ENTITIES_API_KEY = os.getenv("ENTITIES_API_KEY")
USER_ID = os.getenv("ENTITIES_USER_ID")
REPORT_FILE = root_dir / "model_compatibility_report.md"

# --- MULTI-PROVIDER MODEL CONFIG ---
# Structure: "Readable_Label": {"id": "INTERNAL_KEY_WITH_PREFIX", "provider": "provider_name"}

REASONING_INSTRUCTIONS = """You are a helpful assistant equipped with specific tools.
RULES:
1. TOOL USE: You have a tool called 'get_flight_times'. If the user asks about flights, you MUST use this tool.
2. REASONING: If you need to think through a problem, use <think> tags or your internal reasoning process visible to the user.
"""


def get_api_key_for_provider(provider: str) -> str:
    """Dynamic key resolver based on provider name."""
    if provider == "together-ai":
        return os.getenv("TOGETHER_API_KEY", "")
    elif provider == "hyperbolic":
        return os.getenv("HYPERBOLIC_API_KEY", "")
    elif provider == "openai":
        return os.getenv("OPENAI_API_KEY", "")
    return ""


# ------------------------------------------------------------------
# 1. Tool Logic (Mock)
# ------------------------------------------------------------------
def get_flight_times(tool_name: str, arguments) -> str:
    """Mock flight-time lookup tool."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except:
            return json.dumps({"status": "error", "message": "Invalid JSON"})

    return json.dumps(
        {
            "status": "success",
            "duration": "4h 30m",
            "departure_time": "10:00 AM PST",
            "arrival_time": "06:30 PM EST",
        }
    )


# ------------------------------------------------------------------
# 2. Report Manager
# ------------------------------------------------------------------
class ReportManager:
    @staticmethod
    def update_report(new_results: List[Dict]):
        """Reads existing MD, updates specific rows, writes back."""
        file_path = Path(REPORT_FILE)

        header_lines = [
            "# 🧪 Model Compatibility Report",
            f"**Last Update:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            # ADDED: Endpoint ID Column
            "| Model Name | Provider | Endpoint ID | Inference | Reasoning | Tools | Last Run | Notes |",
            "| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- |",
        ]

        existing_rows = {}

        # 1. Read existing file
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    for line in lines:
                        if line.strip().startswith("| **"):
                            try:
                                # Key off the Model Name (first column)
                                parts = line.split("|")
                                name = parts[1].replace("**", "").strip()
                                existing_rows[name] = line.strip()
                            except IndexError:
                                pass
            except Exception as e:
                print(f"{RED}[!] Error reading existing report: {e}{RESET}")

        # 2. Update/Insert new results
        for res in new_results:
            inf_icon = "✅" if res["inference_ok"] else "❌"
            reas_icon = "🧠" if res["reasoning_detected"] else "—"
            tool_icon = "✅" if res["tool_call_ok"] else "❌"
            if not res["inference_ok"]:
                tool_icon = "—"

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            note = res["error_msg"] if res["error_msg"] else "OK"

            # Format: | Name | Provider | ID | Inf | Reas | Tool | Time | Note |
            # Added res['id'] in code-ticks
            row = f"| **{res['name']}** | {res['provider']} | `{res['id']}` | {inf_icon} | {reas_icon} | {tool_icon} | {timestamp} | {note} |"
            existing_rows[res["name"]] = row

        # 3. Write Back
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(header_lines) + "\n")
            for name in sorted(existing_rows.keys()):
                f.write(existing_rows[name] + "\n")

        print(f"\n{GREEN}[✓] Report updated: {file_path}{RESET}")


# ------------------------------------------------------------------
# 3. Test Logic
# ------------------------------------------------------------------
class ModelTester:
    def __init__(self, model_label: str, config: Dict):
        self.model_label = model_label
        self.model_id = config["id"]
        self.provider = config["provider"]
        self.client = Entity(base_url=BASE_URL, api_key=ENTITIES_API_KEY)
        self.assistant_id: Optional[str] = None
        self.user_id = USER_ID
        self.provider_api_key = get_api_key_for_provider(self.provider)

    def setup(self) -> Tuple[bool, str]:
        if not self.provider_api_key:
            return False, f"Missing API Key for {self.provider}"

        try:
            print(
                f"{YELLOW}[*] [{self.model_label}] Creating Assistant ({self.provider})...{RESET}"
            )

            assistant = self.client.assistants.create_assistant(
                name=f"Bench_{self.model_label}",
                instructions=REASONING_INSTRUCTIONS,
                model=self.model_id,
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "get_flight_times",
                            "description": "Get flight times",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "departure": {"type": "string"},
                                    "arrival": {"type": "string"},
                                },
                                "required": ["departure", "arrival"],
                            },
                        },
                    },
                    {"type": "code_interpreter"},
                ],
            )

            self.assistant_id = assistant.id
            return True, None
        except Exception as e:
            return False, str(e)

    def run_benchmark(self) -> Dict:
        result = {
            "name": self.model_label,
            "id": self.model_id,
            "provider": self.provider,
            "inference_ok": False,
            "reasoning_detected": False,
            "tool_call_ok": False,
            "error_msg": "",
        }

        # --- Test 1: Reasoning / Inference ---
        print(
            f"\n{YELLOW}--- Stage 1: Inference & Reasoning ({self.model_label}) ---{RESET}"
        )
        try:
            thread = self.client.threads.create_thread(participant_ids=[self.user_id])
            self.client.messages.create_message(
                thread_id=thread.id,
                role="user",
                content="Calculate Fibonacci recursively. Explain why iterative is better.",
                assistant_id=self.assistant_id,
            )
            run = self.client.runs.create_run(
                assistant_id=self.assistant_id, thread_id=thread.id
            )

            flags = self._stream_and_analyze(thread.id, run.id, timeout=45.0)

            if flags["has_error"]:
                result["error_msg"] = "Stream Error during Inference"
            else:
                result["inference_ok"] = flags["has_content"] or flags["has_reasoning"]
                result["reasoning_detected"] = flags["has_reasoning"]

        except Exception as e:
            result["error_msg"] = f"Inference Exception: {str(e)[:50]}"
            return result

        # --- Test 2: Tools ---
        if result["inference_ok"]:
            print(f"\n{YELLOW}--- Stage 2: Tool Calls ({self.model_label}) ---{RESET}")
            try:
                thread = self.client.threads.create_thread(
                    participant_ids=[self.user_id]
                )
                self.client.messages.create_message(
                    thread_id=thread.id,
                    role="user",
                    content="Fetch flight times between LAX and JFK.",
                    assistant_id=self.assistant_id,
                )
                run = self.client.runs.create_run(
                    assistant_id=self.assistant_id, thread_id=thread.id
                )

                flags = self._stream_and_analyze(thread.id, run.id, timeout=30.0)

                if flags["has_tool_call"]:
                    print(f"\n{YELLOW}[*] Executing Tool Logic...{RESET}")
                    handled = self.client.runs.poll_and_execute_action(
                        run_id=run.id,
                        thread_id=thread.id,
                        assistant_id=self.assistant_id,
                        tool_executor=get_flight_times,
                        actions_client=self.client.actions,
                        messages_client=self.client.messages,
                        timeout=45.0,
                    )

                    if handled:
                        print(f"{YELLOW}[*] Streaming Final Response...{RESET}")
                        flags_final = self._stream_and_analyze(
                            thread.id, run.id, timeout=30.0
                        )
                        if flags_final["has_content"]:
                            result["tool_call_ok"] = True
                else:
                    print(f"{RED}[!] Tool not triggered.{RESET}")

            except Exception as e:
                result["error_msg"] = f"Tool Exception: {str(e)[:50]}"

        return result

    def _stream_and_analyze(self, thread_id, run_id, timeout) -> Dict:
        flags = {
            "has_reasoning": False,
            "has_content": False,
            "has_tool_call": False,
            "has_error": False,
        }

        sync_stream = self.client.synchronous_inference_stream

        sync_stream.setup(
            user_id=self.user_id,
            thread_id=thread_id,
            assistant_id=self.assistant_id,
            message_id="",
            run_id=run_id,
            api_key=self.provider_api_key,
        )

        current_mode = None

        try:
            for chunk in sync_stream.stream_chunks(
                provider=self.provider,  # Dynamic provider string
                model=self.model_id,
                timeout_per_chunk=timeout,
            ):
                ctype = chunk.get("type")
                content = chunk.get("content", "")

                if ctype == "reasoning":
                    flags["has_reasoning"] = True
                elif ctype == "content":
                    flags["has_content"] = True
                elif ctype in ["tool_name", "function_call", "call_arguments"]:
                    flags["has_tool_call"] = True
                elif ctype == "error":
                    flags["has_error"] = True

                # Visuals
                if ctype == "reasoning":
                    if current_mode != "reasoning":
                        print(f"\n{CYAN}🤔 [THOUGHT PROCESS]{RESET}\n", end="")
                        current_mode = "reasoning"
                    print(f"{CYAN}{content}{RESET}", end="", flush=True)

                elif ctype == "content":
                    if current_mode != "content":
                        if current_mode == "reasoning":
                            print("\n")
                        print(f"\n{GREEN}🤖 [ANSWER]{RESET}\n", end="")
                        current_mode = "content"
                    print(f"{GREEN}{content}{RESET}", end="", flush=True)

                elif ctype == "tool_name":
                    print(f"\n{YELLOW}🛠  [TOOL DETECTED]: {content}{RESET}", end="")
                    current_mode = "tool"

                elif ctype == "call_arguments":
                    print(f"{YELLOW}{content}{RESET}", end="", flush=True)

            print()

        except Exception as e:
            print(f"\n{RED}[!] Stream Error: {e}{RESET}")
            flags["has_error"] = True

        return flags


# ------------------------------------------------------------------
# 4. Main Execution
# ------------------------------------------------------------------
def main(models):
    if not USER_ID:
        print(f"{RED}CRITICAL: Missing USER_ID in .env{RESET}")
        return

    print(f"Starting Benchmark for {len(models)} models...\n")

    for label, config in models.items():
        tester = ModelTester(label, config)

        # 1. Setup
        ok, err = tester.setup()
        if not ok:
            print(f"{RED}Failed setup for {label}: {err}{RESET}")
            ReportManager.update_report(
                [
                    {
                        "name": label,
                        "provider": config["provider"],
                        "id": config["id"],
                        "inference_ok": False,
                        "reasoning_detected": False,
                        "tool_call_ok": False,
                        "error_msg": f"Setup Failed: {err}",
                    }
                ]
            )
            continue

        # 2. Run Tests
        res = tester.run_benchmark()

        # 3. Update Report
        ReportManager.update_report([res])

        time.sleep(2)


if __name__ == "__main__":
    main(models=TOGETHER_AI_MODELS)
