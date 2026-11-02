"""Day 11: the explanation texts and the OpenAI call behind them (no database, no network)."""

from types import SimpleNamespace

import app.integrations.openai_client as openai_client
from app.core.config import settings
from app.services.explanations import question_digest, standard_explanation


def test_a_right_answer_is_confirmed():
    text = standard_explanation("print()", "print()", True, "Functions")
    assert "Correct" in text and "print()" in text


def test_a_wrong_answer_names_the_right_one_and_the_choice():
    text = standard_explanation("print()", "echo()", False, "Functions")
    assert "print()" in text and "echo()" in text and "Functions" in text


def test_an_unanswered_question_says_so():
    text = standard_explanation("print()", None, False, "Functions")
    assert "not answered" in text.lower() and "print()" in text


def test_the_digest_changes_when_the_question_or_its_answer_changes():
    base = question_digest("Q?", [("a", True), ("b", False)])
    assert base == question_digest("Q?", [("a", True), ("b", False)])
    assert base != question_digest("Q2?", [("a", True), ("b", False)])
    assert base != question_digest("Q?", [("a", False), ("b", True)])
    assert base != question_digest("Q?", [("a", True), ("c", False)])


def test_no_key_means_no_ai_call(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(openai_client, "_client", None)
    assert openai_client.explain_answer("Python", "Lists", "Q?", ["a", "b"], "a") is None
    assert openai_client._client is None


class _FakeCompletions:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        message = SimpleNamespace(content=self.answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _fake_client(monkeypatch, completions):
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(openai_client, "get_client", lambda: client)


def test_the_ai_is_told_the_question_the_options_and_the_right_answer(monkeypatch):
    completions = _FakeCompletions(answer="  Lists keep order.  ")
    _fake_client(monkeypatch, completions)
    text = openai_client.explain_answer(
        "Python", "Lists", "Which keeps order?", ["list", "set"], "list"
    )
    assert text == "Lists keep order."
    call = completions.calls[0]
    assert call["model"] == settings.OPENAI_EXPLANATION_MODEL
    prompt = " ".join(m["content"] for m in call["messages"])
    for part in ("Which keeps order?", "list", "set", "Lists", "Python"):
        assert part in prompt


def test_an_ai_error_or_an_empty_answer_gives_none(monkeypatch):
    _fake_client(monkeypatch, _FakeCompletions(error=RuntimeError("down")))
    assert openai_client.explain_answer("Python", "Lists", "Q?", ["a"], "a") is None
    _fake_client(monkeypatch, _FakeCompletions(answer="   "))
    assert openai_client.explain_answer("Python", "Lists", "Q?", ["a"], "a") is None
