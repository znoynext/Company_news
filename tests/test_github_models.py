import json

import httpx
import pytest

from dividend_monitor.deduplication import fingerprint
from dividend_monitor.github_models import (
    GitHubModelsClient,
    GitHubModelsUnavailable,
    client_from_environment,
    filter_from_environment,
)
from dividend_monitor.models import Publication


def _publication(title: str = "New financial results") -> Publication:
    return Publication(
        source_id="fixture",
        company="Example Corp",
        ticker="EXM",
        category="news",
        title=title,
        description="<b>Reference text</b> with corporate details.",
        published_at="2026-07-13T12:00:00Z",
    )


def _response(results: list[dict[str, str]]) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps({"results": results})}}]}
    )


def test_enhance_batch_uses_github_models_and_maps_results_by_id() -> None:
    first, second = _publication("First"), _publication("Second")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://models.github.ai/inference/chat/completions"
        assert request.headers["authorization"] == "Bearer temporary-token"
        payload = json.loads(request.content)
        assert payload["model"] == "openai/gpt-4o"
        assert payload["response_format"]["type"] == "json_schema"
        assert "Reference text" in payload["messages"][1]["content"]
        return _response(
            [
                {"id": fingerprint(second), "summary": "Вторая новость.", "importance": "high"},
                {"id": fingerprint(first), "summary": "Первая новость.", "importance": "low"},
            ]
        )

    client = GitHubModelsClient(
        "temporary-token", batch_size=2, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    enhanced = client.enhance_batch([first, second])

    assert enhanced[fingerprint(first)].ai_summary == "Первая новость."
    assert enhanced[fingerprint(second)].importance == "high"


def test_enhance_batch_ignores_unknown_and_duplicate_ids() -> None:
    publication = _publication()
    response = _response(
        [
            {"id": "unknown", "summary": "Не использовать.", "importance": "high"},
            {"id": fingerprint(publication), "summary": "Корректно.", "importance": "medium"},
            {"id": fingerprint(publication), "summary": "Дубликат.", "importance": "low"},
        ]
    )
    client = GitHubModelsClient(
        "temporary-token", client=httpx.Client(transport=httpx.MockTransport(lambda _: response))
    )

    enhanced = client.enhance_batch([publication])

    assert list(enhanced) == [fingerprint(publication)]
    assert enhanced[fingerprint(publication)].ai_summary == "Корректно."


def test_enhance_batch_rejects_numeric_claim_with_unsupported_unit() -> None:
    publication = _publication()
    client = GitHubModelsClient(
        "temporary-token",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: _response(
                    [
                        {
                            "id": fingerprint(publication),
                            "summary": "Компания получила 15 рублей на акцию.",
                            "importance": "high",
                        }
                    ]
                )
            )
        ),
    )

    assert client.enhance_batch([publication]) == {}


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_enhance_fails_closed_for_permanent_http_errors(status_code: int) -> None:
    client = GitHubModelsClient(
        "temporary-token",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status_code))),
    )

    with pytest.raises(GitHubModelsUnavailable, match=rf"HTTP {status_code}") as error:
        client.enhance(_publication())

    assert "temporary-token" not in str(error.value)


def test_enhance_retries_temporary_error_and_honours_retry_after() -> None:
    calls = 0
    delays: list[float] = []
    publication = _publication()

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return _response(
            [{"id": fingerprint(publication), "summary": "Готово.", "importance": "medium"}]
        )

    client = GitHubModelsClient(
        "temporary-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=delays.append,
    )

    assert client.enhance(publication).ai_summary == "Готово."
    assert calls == 2
    assert delays == [3.0]


def test_enhance_rejects_invalid_model_output() -> None:
    client = GitHubModelsClient(
        "temporary-token",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"choices": [{"message": {"content": "not json"}}]}
                )
            )
        ),
    )

    with pytest.raises(GitHubModelsUnavailable, match="invalid completion"):
        client.enhance(_publication())


def test_enhance_accepts_json_inside_markdown_fence() -> None:
    publication = _publication()
    body = json.dumps(
        {
            "results": [
                {
                    "id": fingerprint(publication),
                    "summary": "Компания опубликовала отчётность.",
                    "importance": "medium",
                }
            ]
        }
    )
    content = f"```json\n{body}\n```"
    client = GitHubModelsClient(
        "temporary-token",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
            )
        ),
    )

    assert client.enhance(publication).ai_summary == "Компания опубликовала отчётность."


def test_environment_configuration_disables_ai_without_token_or_when_requested(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("AI_ENABLED", raising=False)
    assert client_from_environment() is None
    monkeypatch.setenv("GITHUB_TOKEN", "temporary-token")
    monkeypatch.setenv("AI_ENABLED", "false")
    assert client_from_environment() is None


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("AI_ENABLED", "sometimes", "AI_ENABLED"),
        ("AI_BATCH_SIZE", "0", "AI_BATCH_SIZE"),
        ("AI_TIMEOUT_SECONDS", "0", "AI_TIMEOUT_SECONDS"),
        ("AI_MIN_IMPORTANCE", "urgent", "AI_MIN_IMPORTANCE"),
    ],
)
def test_environment_configuration_rejects_invalid_values(
    monkeypatch, name, value, message
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "temporary-token")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        if name == "AI_MIN_IMPORTANCE":
            filter_from_environment()
        else:
            client_from_environment()
