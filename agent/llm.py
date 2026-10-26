"""JSON completions from Muse Spark Open (Baseten) with Muse Spark (Meta API) as fallback.

Spark Open on Baseten has no JSON mode, so every reply is parsed and validated with pydantic, and
validation errors are fed back for a bounded number of repair attempts.
"""

import base64
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Literal, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from agent.config import get_settings

log = logging.getLogger(__name__)

Provider = Literal["baseten", "meta"]
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


def default_provider() -> Provider:
    return "baseten" if get_settings().baseten_api_key else "meta"


def _client(provider: Provider) -> tuple[OpenAI, str]:
    s = get_settings()
    if provider == "baseten":
        if not s.baseten_api_key:
            raise LLMError("BASETEN_API_KEY is not set")
        key, url, model = s.baseten_api_key, s.baseten_base_url, s.baseten_model
    else:
        if not s.meta_api_key:
            raise LLMError("META_API_KEY is not set")
        key, url, model = s.meta_api_key, s.meta_api_base_url, s.meta_spark_model
    return OpenAI(base_url=url, api_key=key.get_secret_value()), model


def image_part(path: str | Path) -> dict:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _extract_json(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return text[start : end + 1]


def complete_json(
    system: str,
    user_content: list[dict],
    model_cls: type[T],
    provider: Provider | None = None,
    max_repairs: int = 2,
) -> T:
    provider = provider or default_provider()
    client, model = _client(provider)
    schema = json.dumps(model_cls.model_json_schema(), ensure_ascii=False)
    messages: list[dict] = [
        {
            "role": "system",
            "content": f"{system}\n\nReply with one JSON object only, matching this JSON Schema:\n"
            f"{schema}",
        },
        {"role": "user", "content": user_content},
    ]
    for attempt in range(max_repairs + 1):
        resp = client.chat.completions.create(model=model, messages=messages)
        text = resp.choices[0].message.content or ""
        try:
            return model_cls.model_validate_json(_extract_json(text))
        except (ValueError, ValidationError) as err:
            log.warning("%s reply failed validation (attempt %d): %s", provider, attempt + 1, err)
            messages += [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": f"That reply was invalid: {err}\nReturn the corrected JSON object only.",
                },
            ]
    raise LLMError(f"{provider}: no valid {model_cls.__name__} after {max_repairs + 1} attempts")
