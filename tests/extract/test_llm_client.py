"""Tests for the model wrapper (src.llm.client) with the SDK replaced: key, retries, parsing. No network."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.extract.readings import DocumentReading
from src.llm import client as llm_client
from src.llm.client import Gemini, LLMError, Part, api_keys


class FakeModels:
    def __init__(self, answers):
        self.answers, self.calls, self.calls_by_key = list(answers), [], []

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def gemini(monkeypatch, answers, keys=("key-a",), **kw) -> tuple[Gemini, FakeModels]:
    """A Gemini whose every key's client answers from one shared `FakeModels`, recording which key each call used."""
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    g = Gemini(keys=list(keys), **kw)
    models = FakeModels(answers)
    g._clients = [SimpleNamespace(models=SimpleNamespace(
        generate_content=lambda n=n, **call: models.calls_by_key.append(n) or models.generate_content(**call)))
        for n in range(len(keys))]
    return g, models


def reply(text: str, parsed=None):
    return SimpleNamespace(text=text, parsed=parsed, usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5))


def test_a_missing_key_is_an_error(monkeypatch):
    for name in [k for k in llm_client.os.environ if k.startswith("GOOGLE_API_KEY")]:
        monkeypatch.delenv(name)
    with pytest.raises(LLMError, match="GOOGLE_API_KEY"):
        Gemini()


def test_keys_are_the_plain_one_then_the_numbered_ones_without_repeats():
    env = {"GOOGLE_API_KEY_2": "b", "GOOGLE_API_KEY_10": "c", "GOOGLE_API_KEY_1": "a", "GOOGLE_API_KEY": "a",
           "GOOGLE_API_KEY_3": " ", "OTHER": "x"}
    assert api_keys(env) == ["a", "b", "c"]
    assert api_keys({}) == []


def test_keys_take_turns_and_a_retry_goes_to_the_next_key(monkeypatch):
    ok = '{"kind": "spec", "items": []}'
    g, models = gemini(monkeypatch, [reply(ok), reply(ok), RuntimeError("429"), reply(ok)], keys=("a", "b"))
    for _ in range(3):
        g.generate("extract_document", [], DocumentReading)
    assert models.calls_by_key == [0, 1, 0, 1]  # the third call failed on key 1 (index 0) and went on with key 2


def test_the_model_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    g, _ = gemini(monkeypatch, [])
    assert g.model == "gemini-test"


def test_the_answer_is_parsed_into_the_schema_at_temperature_zero_with_the_rules_as_system_instruction(monkeypatch):
    g, models = gemini(monkeypatch, [reply('{"kind": "label", "items": []}')])
    result = g.generate("extract_document", [Part(text="hello"), Part(data=b"x", mime="image/png")], DocumentReading)
    assert result == DocumentReading(kind="label", items=[])
    _, contents, config = models.calls[0]
    assert config.temperature == 0 and config.response_schema is DocumentReading
    assert "Never fill a value" in config.system_instruction and len(contents) == 2  # the document only


def test_failures_are_retried_then_reported(monkeypatch):
    g, models = gemini(monkeypatch, [RuntimeError("503"), reply('{"kind": "spec", "items": []}')])
    assert g.generate("extract_document", [], DocumentReading).kind == "spec" and len(models.calls) == 2
    g, models = gemini(monkeypatch, [RuntimeError("503 UNAVAILABLE {'message': 'high demand'}")] * 5)
    with pytest.raises(LLMError, match="^Gemini đang quá tải"):  # in Vietnamese, without the raw JSON
        g.generate("extract_document", [], DocumentReading)
    assert len(models.calls) == 5
    g, _ = gemini(monkeypatch, [RuntimeError("bad request " + "x" * 500)] * 5)
    with pytest.raises(LLMError) as err:
        g.generate("extract_document", [], DocumentReading)
    assert str(err.value).startswith("gọi ") and len(str(err.value)) < 260


def test_an_answer_outside_the_schema_is_an_error(monkeypatch):
    g, _ = gemini(monkeypatch, [reply('{"kind": "poem"}')] * llm_client.RETRIES)
    with pytest.raises(LLMError, match="schema"):
        g.generate("extract_document", [], DocumentReading)
