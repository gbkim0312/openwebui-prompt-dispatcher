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
        payload = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "skill_ids": list(request.skill_ids),
            "tool_ids": list(request.tool_ids),
            "required_tool_ids": list(request.required_tool_ids),
            "stream": False,
        }
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
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise OpenWebUiError("Open WebUI generation failed") from exc

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
