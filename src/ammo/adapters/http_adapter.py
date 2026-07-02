"""HTTP adapter — the paid-API route for real execution.

Constitution rule 4 is structural here: the adapter **never stores the key**.
It holds only the env var NAME and reads the value inside ``execute`` at call
time — nothing secret lives on the object, in run artifacts, or in memory.

Vendor specifics (request/response shapes for the Anthropic Messages API and
the OpenAI chat API) stay inside this adapter (rule 5). Transport is injectable
so every test runs offline; the default uses stdlib ``urllib`` (no new deps).
Real token usage from the response becomes ``Usage(estimated=False)`` and is
priced by the PricingBook as actual spend.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

from ammo.adapters.command_adapter import _build_prompt
from ammo.adapters.contract import AdapterRequest, AdapterResponse, BaseModelAdapter, Usage

# transport: (url, headers, body) -> (status_code, response_json_text)
Transport = Callable[[str, Dict[str, str], Dict[str, Any]], Tuple[int, str]]

_TIMEOUT = 180


def default_transport(url: str, headers: Dict[str, str],
                      body: Dict[str, Any]) -> Tuple[int, str]:
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers={**headers, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, str(exc)


class HttpAdapter(BaseModelAdapter):
    def __init__(self, model_id: str, profile, transport: Optional[Transport] = None):
        super().__init__(model_id)
        self._profile = profile                 # holds env var NAME, never a value
        self._transport = transport or default_transport

    def describe(self) -> dict:
        return {"id": self.model_id, "kind": "http",
                "provider": self._profile.id, "format": self._profile.api_format}

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        prompt = _build_prompt(request)
        api_key = os.environ.get(self._profile.env_var or "", "")
        vendor_model = self._profile.api_models.get(request.model, request.model)

        if self._profile.api_format == "anthropic":
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            body = {"model": vendor_model, "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}]}
        else:  # openai-style chat completions
            headers = {"authorization": f"Bearer {api_key}"}
            body = {"model": vendor_model,
                    "messages": [{"role": "user", "content": prompt}]}

        status, payload = self._transport(self._profile.api_url, headers, body)
        text, usage = self._parse(status, payload)
        return AdapterResponse(
            role=request.role,
            model=request.model,
            output=text,
            confidence=0.0,     # evidence-based confidence is computed elsewhere
            reasoning=f"http:{self._profile.id}",
            usage=usage,
        )

    def _parse(self, status: int, payload: str):
        if status != 200:
            detail = payload.strip().replace("\n", " ")[:200]
            return f"(api error {status}: {detail})", None
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return f"(api error: unparseable response) {payload[:120]}", None

        if self._profile.api_format == "anthropic":
            text = "".join(b.get("text", "") for b in data.get("content", [])
                           if b.get("type") == "text")
            u = data.get("usage") or {}
            usage = Usage(
                input_tokens=int(u.get("input_tokens") or 0)
                + int(u.get("cache_read_input_tokens") or 0)
                + int(u.get("cache_creation_input_tokens") or 0),
                output_tokens=int(u.get("output_tokens") or 0),
                estimated=False,
            )
        else:
            choices = data.get("choices") or [{}]
            text = ((choices[0].get("message") or {}).get("content")) or ""
            u = data.get("usage") or {}
            usage = Usage(
                input_tokens=int(u.get("prompt_tokens") or 0),
                output_tokens=int(u.get("completion_tokens") or 0),
                estimated=False,
            )
        return text.strip(), usage
