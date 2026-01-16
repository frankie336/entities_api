# src/api/entities_api/orchestration/streaming/delta_normalizer.py


class HyperbolicDeltaNormalizer:
    FC_START, FC_END = "<fc>", "</fc>"
    TH_START, TH_END = "<think>", "</think>"

    @classmethod
    def iter_deltas(cls, raw_stream, run_id):
        buffer = ""
        state = "content"

        for token in raw_stream:
            # --- NEW: Handle both Objects (OpenAI) and Raw Strings (Custom SDKs) ---
            seg = ""
            if isinstance(token, str):
                seg = token
            elif hasattr(token, "choices") and token.choices:
                delta = token.choices[0].delta
                seg = getattr(delta, "content", "") or ""

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
