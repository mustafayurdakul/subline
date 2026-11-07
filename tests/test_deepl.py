from __future__ import annotations

from types import SimpleNamespace

import pytest

from gametl.translate.base import TranslationError, TranslationRequest
from gametl.translate.deepl import CONTEXT_CHARS, FREE_URL, PRO_URL, DeepLTranslator, context_text, deepl_code


class StubSession:
    def __init__(self, status: int = 200, translations=None, text: str = "err") -> None:
        self.status = status
        self.translations = translations
        self.text = text
        self.calls: list[dict] = []

    def post(self, url, json, headers, timeout):
        self.calls.append({"url": url, "json": json, "headers": headers})
        payload = {
            "translations": self.translations
            if self.translations is not None
            else [{"detected_source_language": "EN", "text": f"TR:{t}"} for t in json["text"]]
        }
        return SimpleNamespace(status_code=self.status, json=lambda: payload, text=self.text)


def test_codes() -> None:
    assert deepl_code("en") == "EN" and deepl_code("tr") == "TR"
    assert deepl_code("japan") == "JA" and deepl_code("ch") == "ZH" and deepl_code("chinese_cht") == "ZH"
    assert deepl_code("no") == "NB" and deepl_code(" sk ") == "SK"
    assert deepl_code("German") == "DE"  # a typed name, not "GE"
    assert deepl_code(None) is None and deepl_code("  ") is None


def test_an_unknown_source_or_a_script_is_left_for_deepl_to_detect() -> None:
    assert deepl_code("xx") is None
    assert deepl_code("devanagari") is None  # not "DE" (German)
    assert deepl_code("cyrillic") is None  # Russian, Ukrainian, Bulgarian, ...: not forced to RU
    assert deepl_code("xx", target=True) == "XX"  # a target passes through for DeepL to judge
    session = StubSession()
    DeepLTranslator(auth_key="k", session=session).translate(TranslationRequest(["Привіт"], source_lang="cyrillic"))
    assert "source_lang" not in session.calls[0]["json"]


def test_target_codes_name_a_variant_where_deepl_requires_one() -> None:
    assert deepl_code("en", target=True) == "EN-US" and deepl_code("pt", target=True) == "PT-PT"
    assert deepl_code("zh", target=True) == "ZH-HANS"
    assert deepl_code("tr", target=True) == "TR"
    assert deepl_code("en-GB", target=True) == "EN-GB"  # a chosen variant passes through
    assert deepl_code("en-GB") == "EN"  # source_lang takes bare codes only
    assert deepl_code("pt-BR") == "PT"
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
    assert DeepLTranslator(auth_key="abc", session=session).url == PRO_URL


def test_a_wrapped_sentence_goes_as_one_paragraph() -> None:
    """DeepL splits at line breaks by default: a subtitle wrapped over two
    lines would be translated as two fragments."""
    session = StubSession()
    translator = DeepLTranslator(auth_key="k", session=session)
    out = translator.translate(TranslationRequest(["Where were you\nwhen the lights  went out?"], target_lang="tr"))
    assert session.calls[0]["json"]["text"] == ["Where were you when the lights went out?"]
    assert out == ["TR:Where were you when the lights went out?"]


def test_key_and_quota_errors_read_plainly_and_ask_for_a_longer_pause() -> None:
    def failure(status: int) -> TranslationError:
        translator = DeepLTranslator(auth_key="k", session=StubSession(status=status, text='{"message": "x"}'))
        with pytest.raises(TranslationError) as caught:
            translator.translate(TranslationRequest(["a"], target_lang="tr"))
        return caught.value

    rejected, quota, busy, other = failure(403), failure(456), failure(429), failure(500)
    assert str(rejected) == "DeepL rejected the key: check it on the Translation page"
    assert str(quota) == "DeepL monthly quota used up"
    assert rejected.retry_after >= 60 and quota.retry_after >= 60
    assert str(busy) == "DeepL is busy, retrying" and busy.retry_after == 0
    assert str(other).startswith("DeepL HTTP 500:") and other.retry_after == 0


def test_errors_raise_translation_error() -> None:
    with pytest.raises(TranslationError, match="Add your DeepL key on the Translation page"):
        DeepLTranslator(session=StubSession())
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
    # The lines being translated go in the context with their speakers, after the earlier lines.
    translator.translate(
        TranslationRequest(["Go.", "Where?"], target_lang="tr", context=context[:1], speakers=["Casey", ""])
    )
    assert session.calls[2]["json"]["context"] == "Hemingway is waiting at the lodge.\nCasey: Go."
    assert session.calls[2]["json"]["text"] == ["Go.", "Where?"]  # the name never enters the text


def test_context_keeps_the_newest_lines_within_the_budget() -> None:
    long = "x" * (CONTEXT_CHARS - 10)
    pairs = [("old line", "t"), (long, "t"), ("", "t"), ("newest", "t")]
    assert context_text(pairs) == f"{long}\nnewest"  # the old line no longer fits; the blank one is skipped
    assert context_text(None) == "" and context_text([]) == ""
