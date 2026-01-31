from __future__ import annotations

from collections import defaultdict

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility

load_dotenv()
LOG = LoggingUtility()


class HyperbolicDeltaNormalizer:
    # Standard XML tags
    FC_START, FC_END = "<fc>", "</fc>"
    TH_START, TH_END = "<think>", "</think>"
    DEC_START, DEC_END = "<decision>", "</decision>"  # [NEW] Decision Tags

    # GPT-OSS / Hermes Channel tags
    CH_ANALYSIS = "<|channel|>analysis"
    CH_COMMENTARY = "<|channel|>commentary"
    CH_FINAL = "<|channel|>final"
    MSG_TAG = "<|message|>"
    CALL_TAG = "<|call|>"

    @classmethod
    def iter_deltas(cls, raw_stream, run_id):
        buffer = ""
        state = "content"

        # State for Native Tool Accumulation
        pending_tool_calls = defaultdict(
            lambda: {"index": 0, "function": {"name": "", "arguments": ""}}
        )

        for token in raw_stream:
            # --- Normalize Input (Universal Adapter) ---
            choices = []
            is_dict = isinstance(token, dict)

            if is_dict:
                choices = token.get("choices", [])
                if not choices or not isinstance(choices, list):
                    continue
                delta = choices[0].get("delta", {})
                finish_reason = choices[0].get("finish_reason")
            elif hasattr(token, "choices") and token.choices:
                choices = token.choices
                delta = choices[0].delta
                finish_reason = getattr(choices[0], "finish_reason", None)
            else:
                continue

            # --- 1. Handle Native Reasoning ---
            r_content = (
                delta.get("reasoning_content")
                if is_dict
                else getattr(delta, "reasoning_content", None)
            )
            if r_content:
                yield {"type": "reasoning", "content": r_content, "run_id": run_id}

            # --- 2. Handle Native Tool Calls ---
            t_calls = (
                delta.get("tool_calls")
                if is_dict
                else getattr(delta, "tool_calls", None)
            )
            if t_calls:
                for tc in t_calls:
                    if is_dict:
                        t_index = tc.get("index", 0)
                        fn = tc.get("function", {})
                        fn_name = fn.get("name")
                        fn_args = fn.get("arguments", "")
                    else:
                        t_index = tc.index
                        fn = tc.function
                        fn_name = getattr(fn, "name", None)
                        fn_args = getattr(fn, "arguments", "")

                    tool_data = pending_tool_calls[t_index]

                    # Accumulate Name
                    if fn_name:
                        tool_data["function"]["name"] += fn_name
                        yield {
                            "type": "call_arguments",
                            "content": fn_name,
                            "run_id": run_id,
                        }

                    # Accumulate Arguments
                    if fn_args:
                        tool_data["function"]["arguments"] += fn_args
                        yield {
                            "type": "call_arguments",
                            "content": fn_args,
                            "run_id": run_id,
                        }

            # --- 3. Handle Standard Content ---
            seg = (
                delta.get("content", "") if is_dict else getattr(delta, "content", "")
            ) or ""

            # --- 4. Tool Completion Trigger (Explicit) ---
            if finish_reason == "tool_calls":
                for idx, data in list(pending_tool_calls.items()):
                    name = data["function"]["name"]
                    args = data["function"]["arguments"]
                    if name:
                        yield {
                            "type": "tool_call",
                            "content": {"name": name, "arguments": args},
                            "run_id": run_id,
                        }
                pending_tool_calls.clear()

            if not seg:
                continue

            buffer += seg

            # ==================================================================
            # ⚡ REAL-TIME OPTIMISTIC STATE MACHINE ⚡
            # ==================================================================
            while buffer:
                yielded_something = False

                # -----------------------------------------------------------
                # STATE: CONTENT
                # -----------------------------------------------------------
                if state == "content":
                    if "<" not in buffer:
                        yield {"type": "content", "content": buffer, "run_id": run_id}
                        buffer = ""
                        break

                    lt_idx = buffer.find("<")
                    if lt_idx > 0:
                        yield {
                            "type": "content",
                            "content": buffer[:lt_idx],
                            "run_id": run_id,
                        }
                        buffer = buffer[lt_idx:]

                    all_tags = [
                        (cls.CH_ANALYSIS, "channel_reasoning"),
                        (cls.CH_COMMENTARY, "channel_tool_meta"),
                        (cls.CH_FINAL, None),
                        (cls.MSG_TAG, None),
                        (cls.FC_START, "fc"),
                        (cls.TH_START, "think"),
                        (cls.DEC_START, "decision"),  # [NEW] Check for <decision>
                    ]

                    match_found = False
                    for tag, new_state in all_tags:
                        if buffer.startswith(tag):
                            if new_state:
                                state = new_state
                            buffer = buffer[len(tag) :]
                            yielded_something = True
                            match_found = True
                            break
                    if match_found:
                        continue

                    is_partial = any(tag.startswith(buffer) for tag, _ in all_tags)

                    if is_partial:
                        break
                    else:
                        yield {
                            "type": "content",
                            "content": buffer[0],
                            "run_id": run_id,
                        }
                        buffer = buffer[1:]
                        yielded_something = True

                # -----------------------------------------------------------
                # STATE: THINK (Reasoning)
                # -----------------------------------------------------------
                elif state == "think":
                    if "<" not in buffer:
                        yield {"type": "reasoning", "content": buffer, "run_id": run_id}
                        buffer = ""
                        break

                    lt_idx = buffer.find("<")
                    if lt_idx > 0:
                        yield {
                            "type": "reasoning",
                            "content": buffer[:lt_idx],
                            "run_id": run_id,
                        }
                        buffer = buffer[lt_idx:]

                    if buffer.startswith(cls.TH_END):
                        buffer = buffer[len(cls.TH_END) :]
                        state = "content"
                        yielded_something = True
                        continue

                    if cls.TH_END.startswith(buffer):
                        break

                    yield {"type": "reasoning", "content": buffer[0], "run_id": run_id}
                    buffer = buffer[1:]
                    yielded_something = True

                # -----------------------------------------------------------
                # [NEW] STATE: DECISION
                # -----------------------------------------------------------
                elif state == "decision":
                    # If </decision> is not imminent, dump buffer to 'decision' type
                    if "<" not in buffer:
                        yield {"type": "decision", "content": buffer, "run_id": run_id}
                        buffer = ""
                        break

                    lt_idx = buffer.find("<")
                    if lt_idx > 0:
                        yield {
                            "type": "decision",
                            "content": buffer[:lt_idx],
                            "run_id": run_id,
                        }
                        buffer = buffer[lt_idx:]

                    # Check for exit tag
                    if buffer.startswith(cls.DEC_END):
                        buffer = buffer[len(cls.DEC_END) :]
                        state = "content"
                        yielded_something = True
                        continue

                    # Handle partial tag (wait for more data)
                    if cls.DEC_END.startswith(buffer):
                        break

                    # Not a tag, yield character
                    yield {"type": "decision", "content": buffer[0], "run_id": run_id}
                    buffer = buffer[1:]
                    yielded_something = True

                # -----------------------------------------------------------
                # STATE: CHANNEL REASONING
                # -----------------------------------------------------------
                elif state == "channel_reasoning":
                    special_markers = [cls.CH_FINAL, cls.CH_COMMENTARY, cls.MSG_TAG]
                    potential_match = False
                    for m in special_markers:
                        if m.startswith(buffer):
                            potential_match = True
                            break

                    if potential_match and len(buffer) < max(
                        len(m) for m in special_markers
                    ):
                        break

                    if buffer.startswith(cls.CH_FINAL):
                        buffer = buffer[len(cls.CH_FINAL) :]
                        state = "content"
                        yielded_something = True
                        continue
                    if buffer.startswith(cls.CH_COMMENTARY):
                        buffer = buffer[len(cls.CH_COMMENTARY) :]
                        state = "channel_tool_meta"
                        yielded_something = True
                        continue
                    if buffer.startswith(cls.MSG_TAG):
                        buffer = buffer[len(cls.MSG_TAG) :]
                        yielded_something = True
                        continue

                    yield {"type": "reasoning", "content": buffer[0], "run_id": run_id}
                    buffer = buffer[1:]
                    yielded_something = True

                # -----------------------------------------------------------
                # STATE: TOOL HANDLING
                # -----------------------------------------------------------
                elif state == "channel_tool_meta":
                    if cls.MSG_TAG in buffer:
                        _, post = buffer.split(cls.MSG_TAG, 1)
                        state = "channel_tool_payload"
                        buffer = post
                        yielded_something = True
                    elif cls.CH_FINAL in buffer:
                        state = "content"
                        buffer = ""
                        yielded_something = True
                    else:
                        break

                elif state == "channel_tool_payload":
                    exit_tags = [cls.CALL_TAG, cls.CH_FINAL, cls.CH_ANALYSIS]

                    if any(buffer.startswith(t) for t in exit_tags):
                        matched = next(t for t in exit_tags if buffer.startswith(t))
                        state = (
                            "channel_reasoning"
                            if matched == cls.CH_ANALYSIS
                            else "content"
                        )
                        buffer = buffer[len(matched) :]
                        yielded_something = True
                        continue

                    if any(t.startswith(buffer) for t in exit_tags):
                        break

                    yield {
                        "type": "call_arguments",
                        "content": buffer[0],
                        "run_id": run_id,
                    }
                    buffer = buffer[1:]
                    yielded_something = True

                elif state == "fc":
                    if buffer.startswith(cls.FC_END):
                        buffer = buffer[len(cls.FC_END) :]
                        state = "content"
                        yielded_something = True
                        continue
                    if cls.FC_END.startswith(buffer):
                        break

                    yield {
                        "type": "call_arguments",
                        "content": buffer[0],
                        "run_id": run_id,
                    }
                    buffer = buffer[1:]
                    yielded_something = True

                if not yielded_something:
                    break

        # --- FINALIZATION ---
        if pending_tool_calls:
            for idx, data in list(pending_tool_calls.items()):
                name = data["function"]["name"]
                args = data["function"]["arguments"]
                if name:
                    yield {
                        "type": "tool_call",
                        "content": {"name": name, "arguments": args},
                        "run_id": run_id,
                    }
            pending_tool_calls.clear()

        if buffer:
            if state in ["channel_reasoning", "think"]:
                yield {"type": "reasoning", "content": buffer, "run_id": run_id}
            elif state in ["channel_tool_payload", "fc"]:
                yield {"type": "call_arguments", "content": buffer, "run_id": run_id}
            elif state == "decision":
                yield {"type": "decision", "content": buffer, "run_id": run_id}
            elif state == "content":
                yield {"type": "content", "content": buffer, "run_id": run_id}
