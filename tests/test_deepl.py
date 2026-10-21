from __future__ import annotations

from types import SimpleNamespace

import pytest

from gametl.translate.base import TranslationError, TranslationRequest
from gametl.translate.deepl import FREE_URL, PRO_URL, DeepLTranslator, deepl_code


class StubSession:
    def __init__(self, status: int = 200, translations=None) -> None:
        self.status = status
        self.translations = translations
        self.calls: list[dict] = []

    def post(self, url, json, headers, timeout):
        self.calls.append({"url": url, "json": json, "headers": headers})
        payload = {"translations": self.translations if self.translations is not None else [
            {"detected_source_language": "EN", "text": f"TR:{t}"} for t in json["text"]
        ]}
        return SimpleNamespace(status_code=self.status, json=lambda: payload, text="err")


def test_codes() -> None:
    assert deepl_code("en") == "EN" and deepl_code("tr") == "TR"
    assert deepl_code("japan") == "JA" and deepl_code("ch") == "ZH"
    assert deepl_code("xx-unknown") == "XX"
    assert deepl_code(None) is None


def test_free_and_pro_endpoints_and_request_shape() -> None:
    session = StubSession()
    translator = DeepLTranslator(auth_key="abc:fx", session=session)
    assert translator.url == FREE_URL
    out = translator.translate(TranslationRequest(["Stay close.", "Run!"], source_lang="en", target_lang="tr"))
    assert out == ["TR:Stay close.", "TR:Run!"]
    (call,) = session.calls
    assert call["json"] == {"text": ["Stay close.", "Run!"], "target_lang": "TR", "preserve_formatting": True, "source_lang": "EN"}
    assert call["headers"]["Authorization"] == "DeepL-Auth-Key abc:fx"
    assert translator.calls == 1 and translator.characters == len("Stay close.") + len("Run!")
    assert DeepLTranslator(auth_key="abc", session=session).url == PRO_URL


def test_errors_raise_translation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPL_AUTH_KEY", raising=False)
    with pytest.raises(TranslationError):
        DeepLTranslator(session=StubSession())
    with pytest.raises(TranslationError):
        DeepLTranslator(auth_key="k", session=StubSession(status=456)).translate(TranslationRequest(["a"], target_lang="tr"))
    with pytest.raises(TranslationError):
        DeepLTranslator(auth_key="k", session=StubSession(translations=[])).translate(TranslationRequest(["a"], target_lang="tr"))
    assert DeepLTranslator(auth_key="k", session=StubSession()).translate(TranslationRequest([], target_lang="tr")) == []
