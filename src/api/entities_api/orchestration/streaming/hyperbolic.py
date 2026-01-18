# src/api/entities_api/orchestration/streaming/hyperbolic.py


class HyperbolicDeltaNormalizer:
    FC_START, FC_END = "<fc>", "</fc>"
    TH_START, TH_END = "<think>", "</think>"

    @classmethod
    def iter_deltas(cls, raw_stream, run_id):
        buffer = ""
        state = "content"

        for token in raw_stream:
            seg = ""

            # --- Dictionary Handling (Home-brew Client) ---
            if isinstance(token, dict):
                # FIX: Check for key existence AND non-empty list
                choices = token.get("choices")
                if not choices or not isinstance(choices, list):
                    continue

                delta = choices[0].get("delta", {})

                # A. Handle Native Reasoning (DeepSeek R1 / Llama R1 Distills)
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    yield {"type": "reasoning", "content": reasoning, "run_id": run_id}

                # B. Handle Native Tool Calls (Llama 3.3 style)
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
                # 'and token.choices' already guards against empty lists here
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

            # If no content was found in this chunk, skip to next token
            if not seg:
                continue

            for char in seg:
                buffer += char
                if state == "content":
                    if cls.FC_START.startswith(buffer) or cls.TH_START.startswith(
                        buffer
                    ):
                        if buffer == cls.FC_START:
                            state = "fc"
                            buffer = ""
                        elif buffer == cls.TH_START:
                            state = "think"
                            buffer = ""
                        continue
                    yield {"type": "content", "content": buffer, "run_id": run_id}
                    buffer = ""
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
