import json


class HyperbolicDeltaNormalizer:
    # Standard XML tags
    FC_START, FC_END = "<fc>", "</fc>"
    TH_START, TH_END = "<think>", "</think>"

    # GPT-OSS / Hermes Channel tags
    CH_ANALYSIS = "<|channel|>analysis"
    CH_COMMENTARY = "<|channel|>commentary"
    CH_FINAL = "<|channel|>final"
    MSG_TAG = "<|message|>"
    CALL_TAG = "<|call|>"

    @classmethod
    def iter_deltas(cls, raw_stream, run_id):
        buffer = ""
        # States: "content", "fc", "think", "channel_reasoning", "channel_tool_meta", "channel_tool_payload"
        state = "content"

        for token in raw_stream:
            seg = ""

            # --- Dictionary Handling (Home-brew Client) ---
            if isinstance(token, dict):
                choices = token.get("choices")
                if not choices or not isinstance(choices, list):
                    continue
                delta = choices[0].get("delta", {})

                # Native fields fallback
                if delta.get("reasoning_content"):
                    yield {
                        "type": "reasoning",
                        "content": delta["reasoning_content"],
                        "run_id": run_id,
                    }
                if delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        args = tc.get("function", {}).get("arguments", "")
                        if args:
                            yield {
                                "type": "call_arguments",
                                "content": args,
                                "run_id": run_id,
                            }

                seg = delta.get("content", "") or ""

            # --- Object Handling (Official SDK) ---
            elif hasattr(token, "choices") and token.choices:
                delta = token.choices[0].delta
                seg = getattr(delta, "content", "") or ""
                t_calls = getattr(delta, "tool_calls", None)
                if t_calls:
                    for tc in t_calls:
                        if tc.function and tc.function.arguments:
                            yield {
                                "type": "call_arguments",
                                "content": tc.function.arguments,
                                "run_id": run_id,
                            }

            if not seg:
                continue

            # Character-by-character parsing
            for char in seg:
                buffer += char

                # =================================================================
                # STATE: CONTENT (Normal Text)
                # =================================================================
                if state == "content":
                    # 1. Detect Analysis (Reasoning)
                    if cls.CH_ANALYSIS.startswith(buffer):
                        if buffer == cls.CH_ANALYSIS:
                            state = "channel_reasoning"
                            buffer = ""
                        continue

                    # 2. Detect Commentary (Tool Calls)
                    # Logs show: <|channel|>commentary to=... <|message|>{json}
                    elif cls.CH_COMMENTARY.startswith(buffer):
                        if buffer == cls.CH_COMMENTARY:
                            state = "channel_tool_meta"  # Wait for <|message|>
                            buffer = ""
                        continue

                    # 3. Detect & Swallow Artifacts
                    elif cls.CH_FINAL.startswith(buffer):
                        if buffer == cls.CH_FINAL:
                            buffer = ""  # Swallow final tag
                        continue
                    elif cls.MSG_TAG.startswith(buffer):
                        if buffer == cls.MSG_TAG:
                            buffer = ""  # Swallow isolated message tags
                        continue

                    # 4. Standard XML Fallbacks
                    elif cls.FC_START.startswith(buffer):
                        if buffer == cls.FC_START:
                            state = "fc"
                            buffer = ""
                        continue
                    elif cls.TH_START.startswith(buffer):
                        if buffer == cls.TH_START:
                            state = "think"
                            buffer = ""
                        continue

                    # 5. Yield Buffer as Content
                    yield {"type": "content", "content": buffer, "run_id": run_id}
                    buffer = ""

                # =================================================================
                # STATE: CHANNEL REASONING (<|channel|>analysis ... <|channel|>final)
                # =================================================================
                elif state == "channel_reasoning":
                    # Exit on CH_FINAL or CH_COMMENTARY (sometimes it switches directly)
                    if cls.CH_FINAL in buffer or cls.CH_COMMENTARY in buffer:
                        # Find which tag ended it
                        tag = (
                            cls.CH_FINAL
                            if cls.CH_FINAL in buffer
                            else cls.CH_COMMENTARY
                        )
                        pre, post = buffer.split(tag, 1)

                        clean_pre = pre.replace(cls.MSG_TAG, "")
                        if clean_pre:
                            yield {
                                "type": "reasoning",
                                "content": clean_pre,
                                "run_id": run_id,
                            }

                        buffer = post
                        if tag == cls.CH_COMMENTARY:
                            state = "channel_tool_meta"
                        else:
                            state = "content"
                            # Clean potential message tag at start of content
                            buffer = buffer.replace(cls.MSG_TAG, "")

                    # Check for partial tags (don't yield partials)
                    elif any(
                        cls.CH_FINAL.startswith(buffer[i:]) for i in range(len(buffer))
                    ):
                        continue
                    elif any(
                        cls.CH_COMMENTARY.startswith(buffer[i:])
                        for i in range(len(buffer))
                    ):
                        continue
                    elif any(
                        cls.MSG_TAG.startswith(buffer[i:]) for i in range(len(buffer))
                    ):
                        if buffer == cls.MSG_TAG:
                            buffer = ""  # Swallow inner message tags
                        continue
                    else:
                        # Yield accumulated reasoning
                        clean_buf = buffer.replace(cls.MSG_TAG, "")
                        if clean_buf:
                            yield {
                                "type": "reasoning",
                                "content": clean_buf,
                                "run_id": run_id,
                            }
                        buffer = ""

                # =================================================================
                # STATE: TOOL META (<|channel|>commentary ...waiting for... <|message|>)
                # =================================================================
                elif state == "channel_tool_meta":
                    # We discard everything here (e.g. " to=tool.get_flight_times <|constrain|>json")
                    # until we hit <|message|>, which starts the JSON payload.
                    if cls.MSG_TAG in buffer:
                        _, post = buffer.split(cls.MSG_TAG, 1)
                        state = "channel_tool_payload"
                        buffer = post

                    # Watch for accidental exit
                    elif cls.CH_FINAL in buffer:
                        state = "content"
                        buffer = ""  # Discard meta

                # =================================================================
                # STATE: TOOL PAYLOAD ({JSON} ... <|call|>)
                # =================================================================
                elif state == "channel_tool_payload":
                    # Exit on <|call|> (Hermes specific end of tool call) or new channel
                    exit_tags = [cls.CALL_TAG, cls.CH_FINAL, cls.CH_ANALYSIS]

                    found_tag = None
                    for tag in exit_tags:
                        if tag in buffer:
                            found_tag = tag
                            break

                    if found_tag:
                        pre, post = buffer.split(found_tag, 1)
                        if pre:
                            yield {
                                "type": "call_arguments",
                                "content": pre,
                                "run_id": run_id,
                            }

                        buffer = post
                        if found_tag == cls.CH_ANALYSIS:
                            state = "channel_reasoning"
                        else:
                            state = "content"

                    # Buffer logic
                    elif any(
                        tag.startswith(buffer[i:])
                        for tag in exit_tags
                        for i in range(len(buffer))
                    ):
                        continue
                    else:
                        yield {
                            "type": "call_arguments",
                            "content": buffer,
                            "run_id": run_id,
                        }
                        buffer = ""

                # =================================================================
                # STATE: LEGACY XML (<fc>, <think>)
                # =================================================================
                elif state == "fc":
                    if cls.FC_END in buffer:
                        pre, post = buffer.split(cls.FC_END, 1)
                        if pre:
                            yield {
                                "type": "call_arguments",
                                "content": pre,
                                "run_id": run_id,
                            }
                        state = "content"
                        buffer = post
                    elif any(
                        cls.FC_END.startswith(buffer[i:]) for i in range(len(buffer))
                    ):
                        continue
                    else:
                        yield {
                            "type": "call_arguments",
                            "content": buffer,
                            "run_id": run_id,
                        }
                        buffer = ""

                elif state == "think":
                    if cls.TH_END in buffer:
                        pre, post = buffer.split(cls.TH_END, 1)
                        if pre:
                            yield {
                                "type": "reasoning",
                                "content": pre,
                                "run_id": run_id,
                            }
                        state = "content"
                        buffer = post
                    elif any(
                        cls.TH_END.startswith(buffer[i:]) for i in range(len(buffer))
                    ):
                        continue
                    else:
                        yield {"type": "reasoning", "content": buffer, "run_id": run_id}
                        buffer = ""
