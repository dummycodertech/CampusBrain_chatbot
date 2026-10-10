"""
Robust JSON extraction utility for Campus Brain LLM responses.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Union


def extract_json(raw: str) -> Union[Dict[str, Any], List[Any]]:
    """Extract and parse JSON (dict or list) from raw LLM output.

    Order of attempts:
    1. Raise ValueError on empty or whitespace input.
    2. Try a ```json ... ``` (or ``` ... ```) fenced code block.
    3. Try json.loads on the entire string.
    4. Try the outermost {...} span.
    5. Try the outermost [...] span.
    6. Raise ValueError if nothing parses.
    """
    if not raw or not raw.strip():
        raise ValueError("Empty or whitespace JSON input.")

    text = raw.strip()

    # 1. Try a ```json ... ``` or ``` ... ``` fenced code block
    fence_pattern = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
    for match in fence_pattern.finditer(text):
        candidate = match.group(1).strip()
        if candidate:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                # If content inside fence has surrounding commentary, try outermost braces/brackets
                first_b = candidate.find("{")
                last_b = candidate.rfind("}")
                if first_b != -1 and last_b > first_b:
                    try:
                        p = json.loads(candidate[first_b:last_b + 1])
                        if isinstance(p, (dict, list)):
                            return p
                    except Exception:
                        pass
                first_br = candidate.find("[")
                last_br = candidate.rfind("]")
                if first_br != -1 and last_br > first_br:
                    try:
                        p = json.loads(candidate[first_br:last_br + 1])
                        if isinstance(p, (dict, list)):
                            return p
                    except Exception:
                        pass

    # 2. Try json.loads on the whole string
    try:
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return parsed
    except Exception:
        pass

    # 3. Try the outermost {...} span
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            parsed = json.loads(text[first_brace:last_brace + 1])
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            pass

    # 4. Try the outermost [...] span
    first_bracket = text.find("[")
    last_bracket = text.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        try:
            parsed = json.loads(text[first_bracket:last_bracket + 1])
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            pass

    raise ValueError(f"Could not parse valid JSON from string: {text[:150]!r}")
