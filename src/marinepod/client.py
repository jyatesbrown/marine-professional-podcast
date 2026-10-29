from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Callable, Optional

import httpx

log = logging.getLogger("marinepod.client")

API_BASE = "https://api.elevenlabs.io"
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class ElevenLabsError(Exception):
    pass


class AuthError(ElevenLabsError):
    pass


class MissingKeyError(AuthError):
    pass


@dataclass
class DialogueResult:
    audio: bytes
    request_id: Optional[str]
    character_count: Optional[int]


_SECRETS: set[str] = set()


def _install_redaction(secret: str) -> None:
    """Redact the key from every log record in the process, whichever logger or handler emits it."""
    if not secret or secret in _SECRETS:
        return
    first = not _SECRETS
    _SECRETS.add(secret)
    if not first:
        return
    base = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = base(*args, **kwargs)
        msg = record.getMessage()
        if any(s in msg for s in _SECRETS):
            for s in _SECRETS:
                msg = msg.replace(s, "***")
            record.msg, record.args = msg, ()
        return record

    logging.setLogRecordFactory(factory)


def get_api_key(env: dict | None = None) -> str:
    key = (env if env is not None else os.environ).get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise MissingKeyError(
            "ELEVENLABS_API_KEY is not set. Export it in your shell or put it in a git-ignored .env "
            "file (see .env.example). Dry runs do not need it."
        )
    return key


class ElevenLabsClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = API_BASE,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = 5,
        backoff_base: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 180.0,
    ):
        if not api_key:
            raise MissingKeyError("Empty ElevenLabs API key.")
        self._http = httpx.Client(
            base_url=base_url,
            headers={"xi-api-key": api_key},
            transport=transport,
            timeout=timeout,
        )
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self._sleep = sleep
        _install_redaction(api_key)

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = self._http.request(method, path, **kw)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = e
                log.warning("%s %s: network error (%s), attempt %d/%d", method, path,
                            type(e).__name__, attempt, self.max_attempts)
            else:
                if resp.status_code < 400:
                    return resp
                detail = _detail(resp)
                if resp.status_code in (401, 403):
                    raise AuthError(f"ElevenLabs rejected the API key ({resp.status_code}): {detail}")
                if resp.status_code not in RETRYABLE_STATUS:
                    raise ElevenLabsError(f"{method} {path} failed ({resp.status_code}): {detail}")
                last = ElevenLabsError(f"{resp.status_code}: {detail}")
                log.warning("%s %s: HTTP %d (%s), attempt %d/%d", method, path, resp.status_code,
                            detail[:200], attempt, self.max_attempts)
                retry_after = resp.headers.get("retry-after")
                if retry_after and retry_after.replace(".", "", 1).isdigit() and attempt < self.max_attempts:
                    self._sleep(float(retry_after))
                    continue
            if attempt < self.max_attempts:
                self._sleep(self.backoff_base ** (attempt - 1) + random.uniform(0, 0.5))
        raise ElevenLabsError(f"{method} {path} failed after {self.max_attempts} attempts: {last}")

    def text_to_dialogue(
        self,
        inputs: list[dict],
        model_id: str,
        output_format: str,
        settings: dict | None = None,
        language_code: str | None = None,
        seed: int | None = None,
        previous_text: str | None = None,
        future_text: str | None = None,
        previous_request_ids: list[str] | None = None,
    ) -> DialogueResult:
        body: dict = {"inputs": inputs, "model_id": model_id}
        if settings:
            body["settings"] = {k: v for k, v in settings.items() if v is not None}
        if language_code:
            body["language_code"] = language_code
        if seed is not None:
            body["seed"] = seed
        if previous_text:
            body["previous_text"] = previous_text[-100:]
        if future_text:
            body["future_text"] = future_text[:100]
        if previous_request_ids:
            body["previous_request_ids"] = previous_request_ids[-3:]
        resp = self._request("POST", "/v1/text-to-dialogue", params={"output_format": output_format}, json=body)
        ctype = resp.headers.get("content-type", "")
        if "audio" not in ctype and "octet-stream" not in ctype:
            raise ElevenLabsError(f"Expected audio, got content-type {ctype!r}: {resp.text[:200]}")
        if not resp.content:
            raise ElevenLabsError("Empty audio response.")
        count = resp.headers.get("x-character-count")
        return DialogueResult(
            audio=resp.content,
            request_id=resp.headers.get("request-id"),
            character_count=int(count) if count and count.isdigit() else None,
        )

    def subscription(self) -> dict:
        return self._request("GET", "/v1/user/subscription").json()

    def voices(self) -> list[dict]:
        return self._request("GET", "/v2/voices", params={"page_size": 100}).json().get("voices", [])

    def models(self) -> list[dict]:
        return self._request("GET", "/v1/models").json()


def _detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        d = data.get("detail", data)
        return d if isinstance(d, str) else str(d)
    except Exception:
        return resp.text[:300]
