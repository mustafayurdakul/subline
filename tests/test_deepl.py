from __future__ import annotations

from types import SimpleNamespace

import pytest

from gametl.translate.base import TranslationError, TranslationRequest
from gametl.translate.deepl import CONTEXT_CHARS, FREE_URL, PRO_URL, DeepLTranslator, context_text, deepl_code


class StubSession:
    def __init__(self, status: int = 200, translations=None) -> None:
        self.status = status
        self.translations = translations
        self.calls: list[dict] = []

    def post(self, url, json, headers, timeout):
        self.calls.append({"url": url, "json": json, "headers": headers})
        payload = {
            "translations": self.translations
            if self.translations is not None
            else [{"detected_source_language": "EN", "text": f"TR:{t}"} for t in json["text"]]
        }
        return SimpleNamespace(status_code=self.status, json=lambda: payload, text="err")


def test_codes() -> None:
    assert deepl_code("en") == "EN" and deepl_code("tr") == "TR"
    assert deepl_code("japan") == "JA" and deepl_code("ch") == "ZH"
    assert deepl_code("xx") == "XX"
    assert deepl_code(None) is None


def test_target_codes_name_a_variant_where_deepl_requires_one() -> None:
    assert deepl_code("en", target=True) == "EN-US" and deepl_code("pt", target=True) == "PT-PT"
    assert deepl_code("tr", target=True) == "TR"
    assert deepl_code("en-GB", target=True) == "EN-GB"  # a chosen variant passes through
    assert deepl_code("en-GB") == "EN-GB"
    session = StubSession()
    DeepLTranslator(auth_key="k", session=session).translate(
        TranslationRequest(["Merhaba"], source_lang="tr", target_lang="en")
    )
    assert session.calls[0]["json"]["target_lang"] == "EN-US"
    assert session.calls[0]["json"]["source_lang"] == "TR"


def test_free_and_pro_endpoints_and_request_shape() -> None:
    session = StubSession()
    translator = DeepLTranslator(auth_key="abc:fx", session=session)
    assert translator.url == FREE_URL
    out = translator.translate(TranslationRequest(["Stay close.", "Run!"], source_lang="en", target_lang="tr"))
    assert out == ["TR:Stay close.", "TR:Run!"]
    (call,) = session.calls
    assert call["json"] == {
        "text": ["Stay close.", "Run!"],
        "target_lang": "TR",
        "preserve_formatting": True,
        "source_lang": "EN",
    }
    assert call["headers"]["Authorization"] == "DeepL-Auth-Key abc:fx"
    assert translator.calls == 1 and translator.characters == len("Stay close.") + len("Run!")
    assert DeepLTranslator(auth_key="abc", session=session).url == PRO_URL


def test_errors_raise_translation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPL_AUTH_KEY", raising=False)
    with pytest.raises(TranslationError):
        DeepLTranslator(session=StubSession())
    with pytest.raises(TranslationError):
        DeepLTranslator(auth_key="k", session=StubSession(status=456)).translate(
            TranslationRequest(["a"], target_lang="tr")
        )
    with pytest.raises(TranslationError):
        DeepLTranslator(auth_key="k", session=StubSession(translations=[])).translate(
            TranslationRequest(["a"], target_lang="tr")
        )
    assert (
        DeepLTranslator(auth_key="k", session=StubSession()).translate(TranslationRequest([], target_lang="tr")) == []
    )


def test_recent_source_lines_go_along_as_context() -> None:
    session = StubSession()
    translator = DeepLTranslator(auth_key="k", session=session)
    context = [("Hemingway is waiting at the lodge.", "Hemingway lokantada bekliyor."), ("He said so.", "Öyle dedi.")]
    translator.translate(TranslationRequest(["Go find Hemingway."], target_lang="tr", context=context))
    assert session.calls[0]["json"]["context"] == "Hemingway is waiting at the lodge.\nHe said so."
    translator.translate(TranslationRequest(["Go."], target_lang="tr"))
    assert "context" not in session.calls[1]["json"]  # nothing seen yet: no context field at all


def test_context_keeps_the_newest_lines_within_the_budget() -> None:
    long = "x" * (CONTEXT_CHARS - 10)
    pairs = [("old line", "t"), (long, "t"), ("", "t"), ("newest", "t")]
    assert context_text(pairs) == f"{long}\nnewest"  # the old line no longer fits; the blank one is skipped
    assert context_text(None) == "" and context_text([]) == ""
