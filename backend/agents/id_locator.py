"""Where the identity number is printed on an identity-card crop, so it can be blurred before the crop is shown.

One vision call per document (disk-cached like every model call), structured output with normalized boxes only:
the model is told not to write the digits, and the reply is redacted anyway before it is cached.
"""

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from openai import APIError

from clients.llm import LLMError, complete
from vision.mask import Box, valid_boxes
from vision.text import redact_identity_numbers

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "locate_id_number.md").read_text(encoding="utf-8")
_NUMBER = {"type": "number"}
RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {"name": "id_number_boxes", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["boxes"],
        "properties": {"boxes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["x0", "y0", "x1", "y1"],
            "properties": {"x0": _NUMBER, "y0": _NUMBER, "x1": _NUMBER, "y1": _NUMBER}}}}}},
}

Locator = Callable[[bytes], list[Box] | None]


def locate_id_numbers(image: bytes, *, llm: Callable[..., Any] = complete,
                      overrides: Mapping[str, Any] | None = None) -> list[Box] | None:
    """Boxes around the identity number(s) on one crop; [] if the model saw none; None if the call failed."""
    try:
        resp = llm(PROMPT, task="vision", images=[image], response_format=RESPONSE_FORMAT, overrides=overrides,
                   redact=redact_identity_numbers)
    except (LLMError, APIError):
        return None
    start, end = resp.text.find("{"), resp.text.rfind("}")
    try:
        data = json.loads(resp.text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return valid_boxes(data.get("boxes")) if isinstance(data, dict) else None
