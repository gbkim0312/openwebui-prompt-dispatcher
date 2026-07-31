import time
from uuid import uuid4

import httpx

from prompt_dispatcher.domain.errors import OpenWebUiError
from prompt_dispatcher.domain.job import OpenWebUiRequest, OpenWebUiResponse


class HttpOpenWebUiAdapter:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        verify_tls: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self._url, self._key, self._client = (
            base_url.rstrip("/"),
            api_key,
            client or httpx.Client(verify=verify_tls),
        )

    def generate(self, request: OpenWebUiRequest) -> OpenWebUiResponse:
        if request.skill_ids or request.tool_ids:
            return self._generate_in_chat(request)
        payload = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "stream": False,
        }
        if request.skill_ids:
            payload["skill_ids"] = list(request.skill_ids)
        if request.tool_ids:
            payload["tool_ids"] = list(request.tool_ids)
        if request.required_tool_ids:
            payload["required_tool_ids"] = list(request.required_tool_ids)
        try:
            response = self._client.post(
                f"{self._url}/api/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=request.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"].get("content", "")
            calls = tuple(str(call) for call in data["choices"][0]["message"].get("tool_calls", []))
            return OpenWebUiResponse(
                content=content, model=data.get("model", request.model), tool_calls=calls
            )
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                payload = exc.response.json()
                if isinstance(payload, dict):
                    detail = str(payload.get("detail") or payload.get("message") or "")
            except ValueError:
                pass
            suffix = f": {detail[:500]}" if detail else ""
            raise OpenWebUiError(
                f"Open WebUI generation failed (HTTP {exc.response.status_code}){suffix}"
            ) from exc
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise OpenWebUiError("Open WebUI generation failed") from exc

    def _generate_in_chat(self, request: OpenWebUiRequest) -> OpenWebUiResponse:
        """Use Open WebUI's chat-backed flow so server-side tools can finish."""
        user_id, assistant_id, session_id = (str(uuid4()) for _ in range(3))
        timestamp = int(time.time())
        user_message = {
            "id": user_id,
            "role": "user",
            "content": request.prompt,
            "timestamp": timestamp,
            "models": [request.model],
            "childrenIds": [assistant_id],
        }
        assistant_message = {
            "id": assistant_id,
            "role": "assistant",
            "content": "",
            "parentId": user_id,
            "childrenIds": [],
            "model": request.model,
            "modelName": request.model,
            "modelIdx": 0,
            "done": False,
            "timestamp": timestamp + 1,
        }
        chat = {
            "title": "Prompt Dispatcher 실행",
            "models": [request.model],
            "messages": [user_message, assistant_message],
            "history": {
                "currentId": assistant_id,
                "messages": {user_id: user_message, assistant_id: assistant_message},
            },
        }
        try:
            created = self._client.post(
                f"{self._url}/api/v1/chats/new",
                json={"chat": chat},
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=request.timeout_seconds,
            )
            created.raise_for_status()
            chat_id = str(created.json()["id"])
            payload: dict[str, object] = {
                "chat_id": chat_id,
                "id": assistant_id,
                "session_id": session_id,
                "model": request.model,
                "messages": [{"role": "user", "content": request.prompt}],
                "stream": True,
                "background_tasks": {
                    "title_generation": False,
                    "tags_generation": False,
                    "follow_up_generation": False,
                },
                "features": {
                    "code_interpreter": False,
                    "web_search": False,
                    "image_generation": False,
                    "memory": False,
                },
            }
            if request.skill_ids:
                payload["skill_ids"] = list(request.skill_ids)
            if request.tool_ids:
                payload["tool_ids"] = list(request.tool_ids)
            with self._client.stream(
                "POST",
                f"{self._url}/api/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=request.timeout_seconds,
            ) as response:
                response.raise_for_status()
                for _ in response.iter_bytes():
                    pass
            deadline = time.monotonic() + min(request.timeout_seconds, 90)
            while time.monotonic() < deadline:
                stored = self._client.get(
                    f"{self._url}/api/v1/chats/{chat_id}",
                    headers={"Authorization": f"Bearer {self._key}"},
                    timeout=30,
                )
                stored.raise_for_status()
                data = stored.json()
                chat_data = data.get("chat", data) if isinstance(data, dict) else {}
                history = chat_data.get("history", {}) if isinstance(chat_data, dict) else {}
                messages = history.get("messages", {}) if isinstance(history, dict) else {}
                message = messages.get(assistant_id, {}) if isinstance(messages, dict) else {}
                content = message.get("content", "") if isinstance(message, dict) else ""
                if isinstance(content, str) and content.strip():
                    return OpenWebUiResponse(content=content, model=request.model)
                time.sleep(1)
            raise OpenWebUiError("Open WebUI tool response timed out")
        except httpx.HTTPStatusError as exc:
            raise OpenWebUiError(
                f"Open WebUI chat-backed tool generation failed (HTTP {exc.response.status_code})"
            ) from exc
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise OpenWebUiError("Open WebUI chat-backed tool generation failed") from exc

    def list_models(self) -> tuple[str, ...]:
        models: set[str] = set()
        last_error: Exception | None = None
        # Open WebUI installations can expose provider models through either endpoint.
        for path in ("/api/models", "/api/v1/models"):
            try:
                response = self._client.get(
                    f"{self._url}{path}",
                    headers={"Authorization": f"Bearer {self._key}"},
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()
                records = payload.get("data", payload) if isinstance(payload, dict) else payload
                if not isinstance(records, list):
                    raise TypeError("Unexpected model catalog response")
                models.update(
                    str(item.get("id") or item.get("name"))
                    for item in records
                    if isinstance(item, dict) and (item.get("id") or item.get("name"))
                )
            except (httpx.HTTPError, TypeError, ValueError) as error:
                last_error = error
        if models:
            return tuple(sorted(models))
        raise OpenWebUiError("Unable to load Open WebUI models") from last_error

    def list_capabilities(self) -> dict[str, tuple[dict[str, str], ...]]:
        """Return user-visible Open WebUI skills and tools, tolerating unavailable APIs."""
        catalogs: dict[str, tuple[dict[str, str], ...]] = {}
        for capability_type, path in (("skills", "/api/v1/skills/"), ("tools", "/api/v1/tools/")):
            try:
                response = self._client.get(
                    f"{self._url}{path}",
                    headers={"Authorization": f"Bearer {self._key}"},
                    timeout=30,
                )
                response.raise_for_status()
                records = response.json()
                if not isinstance(records, list):
                    raise TypeError("Unexpected capability catalog response")
                items = {
                    (str(record["id"]), str(record.get("name") or record["id"]))
                    for record in records
                    if isinstance(record, dict) and record.get("id")
                }
                catalogs[capability_type] = tuple(
                    {"id": identifier, "name": name}
                    for identifier, name in sorted(items, key=lambda item: item[1].lower())
                )
            except (httpx.HTTPError, TypeError, ValueError):
                catalogs[capability_type] = ()
        return catalogs


class FakeOpenWebUiClient:
    def __init__(
        self, response_content: str = "fake response", exception: Exception | None = None
    ) -> None:
        self.response_content = response_content
        self.exception = exception
        self.requests: list[OpenWebUiRequest] = []

    def generate(self, request: OpenWebUiRequest) -> OpenWebUiResponse:
        self.requests.append(request)
        if self.exception:
            raise self.exception
        return OpenWebUiResponse(self.response_content, request.model)

    def list_models(self) -> tuple[str, ...]:
        return ("fake-model",)
