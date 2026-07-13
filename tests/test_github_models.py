import json

import httpx
import pytest

from dividend_monitor.github_models import GitHubModelsClient, GitHubModelsUnavailable
from dividend_monitor.models import Publication


def _publication() -> Publication:
    return Publication(
        source_id="fixture",
        company="Example Corp",
        ticker="EXM",
        category="news",
        title="New financial results",
        description="<b>Reference text</b> with corporate details.",
        published_at="2026-07-13T12:00:00Z",
    )


def test_enhance_uses_github_models_and_validates_structured_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://models.github.ai/inference/chat/completions"
        assert request.headers["authorization"] == "Bearer temporary-token"
        payload = json.loads(request.content)
        assert payload["model"] == "microsoft/phi-4-mini-instruct"
        assert payload["response_format"] == {"type": "json_object"}
        assert "Reference text" in payload["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Компания опубликовала финансовые результаты.",
                                    "importance": "high",
                                }
                            )
                        }
                    }
                ]
            },
        )

    client = GitHubModelsClient(
        "temporary-token", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    enhanced = client.enhance(_publication())

    assert enhanced.ai_summary == "Компания опубликовала финансовые результаты."
    assert enhanced.importance == "high"


def test_enhance_fails_closed_on_rate_limit_without_exposing_token() -> None:
    client = GitHubModelsClient(
        "temporary-token",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(429))),
    )

    with pytest.raises(GitHubModelsUnavailable, match="HTTP 429") as error:
        client.enhance(_publication())

    assert "temporary-token" not in str(error.value)


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
    content = """```json
{"summary":"Компания опубликовала отчётность.","importance":"medium"}
```"""
    client = GitHubModelsClient(
        "temporary-token",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
            )
        ),
    )

    enhanced = client.enhance(_publication())

    assert enhanced.ai_summary == "Компания опубликовала отчётность."
    assert enhanced.importance == "medium"
