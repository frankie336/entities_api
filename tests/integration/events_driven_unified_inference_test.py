"""
Automated Model Benchmark: Reasoning & Tool Use (Event-Driven Refactor)
-----------------------------------------------------------------------
1. Loops through specified models.
2. Uses the new SDK Event System (ContentEvent, ToolCallRequestEvent).
3. BEHAVIOR: Matches original Markdown layout (One table per Provider).
4. GUARANTEES ID UNIQUENESS: Deduplicates by Endpoint ID.
"""

import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

# Import definitions
from models import HYPERBOLIC_MODELS, TOGETHER_AI_MODELS

# --- SDK Event Imports ---
from projectdavid import (
    ContentEvent,
    Entity,
    ReasoningEvent,
    StatusEvent,
    ToolCallRequestEvent,
)

from src.api.entities_api.system_message.main_assembly import assemble_instructions

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

tool_instructions = assemble_instructions(include_keys=[])


def get_api_key_for_provider(provider: str) -> str:
    """Dynamic key resolver."""
    p = provider.lower()
    if "together" in p:
        return os.getenv("TOGETHER_API_KEY", "")
    elif "hyperbolic" in p:
        return os.getenv("HYPERBOLIC_API_KEY", "")
    elif "openai" in p:
        return os.getenv("OPENAI_API_KEY", "")
    return ""


# ------------------------------------------------------------------
# 1. Tool Logic (SDK now delivers pre-parsed dict arguments)
# ------------------------------------------------------------------
def get_flight_times(tool_name: str, arguments: dict) -> str:
    """Mock flight-time lookup tool."""
    # Arguments are already a dict thanks to the SDK Event System
    return json.dumps(
        {
            "status": "success",
            "duration": "4h 30m",
            "departure_time": "10:00 AM PST",
            "arrival_time": "06:30 PM EST",
        }
    )


# ------------------------------------------------------------------
# 2. Report Manager (Identical to Original Logic/Layout)
# ------------------------------------------------------------------
class ReportManager:
    @staticmethod
    def update_report(new_results: List[Dict]):
        """
        Updates the MD file with the exact same layout as the original script.
        Deduplicates by ID, groups by Provider.
        """
        file_path = Path(REPORT_FILE)
        rows_by_provider = defaultdict(dict)

        # 1. Read Existing File for Deduplication
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        clean_line = line.strip()
                        if clean_line.startswith("| **"):
                            parts = [p.strip() for p in clean_line.split("|")]
                            if len(parts) >= 4:
                                provider = parts[2].strip()
                                match = re.search(r"`(.*?)`", parts[3])
                                if match:
                                    eid = match.group(1).strip()
                                    rows_by_provider[provider][eid] = clean_line
            except Exception as e:
                print(f"{RED}[!] Error parsing report: {e}{RESET}")

        # 2. Merge New Results
        for res in new_results:
            inf_icon = "✅" if res["inference_ok"] else "❌"
            reas_icon = "🧠" if res["reasoning_detected"] else "—"
            tool_icon = "✅" if res["tool_call_ok"] else "❌"

            if not res["inference_ok"]:
                tool_icon = "—"

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            note = res["error_msg"] if res["error_msg"] else "OK"

            new_row = (
                f"| **{res['name']}** | {res['provider']} | `{res['id']}` | "
                f"{inf_icon} | {reas_icon} | {tool_icon} | {timestamp} | {note} |"
            )
            rows_by_provider[res["provider"]][res["id"]] = new_row

        # 3. Write Report
        table_header_row = "| Model Name | Provider | Endpoint ID | Inference | Reasoning | Tools | Last Run | Notes |"
        table_align_row = "| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- |"
        main_title = [
            "# 🧪 Model Compatibility Report",
            f"**Last Update:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(main_title))
                for provider in sorted(rows_by_provider.keys()):
                    f.write(f"\n## 🟢 Provider: {provider}\n")
                    f.write(f"{table_header_row}\n{table_align_row}\n")
                    rows = sorted(
                        rows_by_provider[provider].values(),
                        key=lambda x: x.split("|")[1].strip().lower(),
                    )
                    f.write("\n".join(rows) + "\n")
            print(f"{GREEN}[✓] Report updated.{RESET}")
        except Exception as e:
            print(f"{RED}[!] Write failed: {e}{RESET}")


# ------------------------------------------------------------------
# 3. Test Logic (Refactored for Events)
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

        # Bind clients immediately for Smart Event execution capability
        if hasattr(self.client, "synchronous_inference_stream"):
            self.client.synchronous_inference_stream.bind_clients(
                self.client.runs, self.client.actions, self.client.messages
            )

    def setup(self) -> Tuple[bool, str]:
        if not self.provider_api_key:
            return False, f"Missing API Key for {self.provider}"

        try:
            print(f"{YELLOW}[*] [{self.model_label}] Creating Assistant...{RESET}")
            assistant = self.client.assistants.create_assistant(
                name=f"Bench_{self.model_label}",
                instructions=tool_instructions,
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
                    }
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

        # Stage 1: Inference & Reasoning
        print(f"\n{YELLOW}--- Stage 1: Inference ({self.model_label}) ---{RESET}")
        try:
            thread = self.client.threads.create_thread(participant_ids=[self.user_id])
            message = self.client.messages.create_message(
                thread_id=thread.id,
                role="user",
                content="Calculate Fibonacci recursively. Explain why iterative is better.",
                assistant_id=self.assistant_id,
            )
            run = self.client.runs.create_run(
                assistant_id=self.assistant_id, thread_id=thread.id
            )

            flags = self._stream_and_analyze(
                thread.id, message.id, run.id, timeout=180.0
            )

            result["inference_ok"] = flags["inference_ok"]
            result["reasoning_detected"] = flags["reasoning_detected"]
            if flags["error"]:
                result["error_msg"] = "Stream Error"

        except Exception as e:
            result["error_msg"] = f"Inference Exception: {str(e)[:50]}"
            return result

        # Stage 2: Tool Calls
        if result["inference_ok"]:
            print(f"\n{YELLOW}--- Stage 2: Tool Calls ({self.model_label}) ---{RESET}")
            try:
                thread = self.client.threads.create_thread(
                    participant_ids=[self.user_id]
                )
                message = self.client.messages.create_message(
                    thread_id=thread.id,
                    role="user",
                    content="Fetch flight times between LAX and JFK.",
                    assistant_id=self.assistant_id,
                )
                run = self.client.runs.create_run(
                    assistant_id=self.assistant_id, thread_id=thread.id
                )

                # Execute Stream 1 (Detection & Execution)
                stream_res = self._stream_and_analyze(
                    thread.id, message.id, run.id, timeout=60.0
                )

                if stream_res["tool_executed"]:
                    print(f"\n{YELLOW}[*] Streaming Final Response...{RESET}")
                    # Execute Stream 2 (Final Answer)
                    final_res = self._stream_and_analyze(
                        thread.id, message.id, run.id, timeout=60.0
                    )
                    if final_res["inference_ok"]:
                        result["tool_call_ok"] = True
                else:
                    print(f"{RED}[!] Tool call not triggered.{RESET}")

            except Exception as e:
                result["error_msg"] = f"Tool Exception: {str(e)[:50]}"

        return result

    def _stream_and_analyze(self, thread_id, message_id, run_id, timeout) -> Dict:
        """New event-driven analysis loop."""
        stats = {
            "inference_ok": False,
            "reasoning_detected": False,
            "tool_executed": False,
            "error": False,
        }

        stream = self.client.synchronous_inference_stream
        stream.setup(
            user_id=self.user_id,
            thread_id=thread_id,
            assistant_id=self.assistant_id,
            message_id=message_id,
            run_id=run_id,
            api_key=self.provider_api_key,
        )

        current_mode = None
        try:
            for event in stream.stream_events(
                provider=self.provider, model=self.model_id, timeout_per_chunk=timeout
            ):

                if isinstance(event, ReasoningEvent):
                    if current_mode != "reasoning":
                        print(f"\n{CYAN}🤔 [THOUGHT PROCESS]{RESET}\n", end="")
                        current_mode = "reasoning"
                        stats["reasoning_detected"] = True
                    print(f"{CYAN}{event.content}{RESET}", end="", flush=True)

                elif isinstance(event, ContentEvent):
                    if current_mode != "content":
                        if current_mode == "reasoning":
                            print("\n")
                        print(f"\n{GREEN}🤖 [ANSWER]{RESET}\n", end="")
                        current_mode = "content"
                        stats["inference_ok"] = True
                    print(f"{GREEN}{event.content}{RESET}", end="", flush=True)

                elif isinstance(event, ToolCallRequestEvent):
                    print(f"\n{YELLOW}🛠  [TOOL DETECTED]: {event.tool_name}{RESET}")
                    # SDK handles the output submission automatically
                    if event.execute(get_flight_times):
                        stats["tool_executed"] = True

                elif isinstance(event, StatusEvent) and event.status == "failed":
                    stats["error"] = True

            print()
        except Exception as e:
            print(f"\n{RED}[!] Stream Error: {e}{RESET}")
            stats["error"] = True

        return stats


# ------------------------------------------------------------------
# 4. Main Execution
# ------------------------------------------------------------------
def main(models_to_run):
    if not USER_ID:
        print(f"{RED}CRITICAL: Missing USER_ID in .env{RESET}")
        return

    print(f"Starting Benchmark for {len(models_to_run)} models...\n")
    ReportManager.update_report([])

    for label, raw_config in models_to_run.items():
        config = (
            raw_config
            if isinstance(raw_config, dict)
            else {"id": raw_config, "provider": "hyperbolic"}
        )
        tester = ModelTester(label, config)

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

        res = tester.run_benchmark()
        ReportManager.update_report([res])
        time.sleep(2)


if __name__ == "__main__":
    main(models_to_run=HYPERBOLIC_MODELS)
