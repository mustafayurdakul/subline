"""The chat transcript: a block's line enters once, follows a reveal or an
OCR correction, gives way to the next line at the same spot, is not
doubled when the line is lost and found again, and ages out; speakers
keep their number. And the speaker split the pipeline feeds it with."""

from __future__ import annotations

from gametl.textutil import split_speaker
from gametl.tracking.transcript import Transcript


def test_split_speaker_takes_a_name_before_the_colon() -> None:
    assert split_speaker("Casey: Where are you going?") == ("Casey", "Where are you going?")
    assert split_speaker("Dr. Darling: It works.") == ("Dr. Darling", "It works.")
    assert split_speaker("SAGA ANDERSON: Stay close.") == ("SAGA ANDERSON", "Stay close.")
    assert split_speaker("CASEY:\nGo.") == ("CASEY", "Go.")  # the name on its own OCR line
    assert split_speaker("Alan: It's like\nthey're coming in.") == ("Alan", "It's like\nthey're coming in.")
    # A sentence with a colon is not a speaker: a lower-case word, three words, nothing after the colon.
    assert split_speaker("note: the door is locked.") == ("", "note: the door is locked.")
    assert split_speaker("The Dark Place Manuscript: page 3") == ("", "The Dark Place Manuscript: page 3")
    assert split_speaker("Casey:") == ("", "Casey:")
    assert split_speaker("Where are you going?") == ("", "Where are you going?")


def test_a_line_enters_once_and_follows_its_block() -> None:
    t = Transcript(lines=4, seconds=20)
    assert t.observe(1, "Casey", "Where are you going?", "Nereye gidiyorsun?", now=0.0) is True
    assert t.observe(1, "Casey", "Where are you going?", "Nereye gidiyorsun?", now=0.1) is False  # the same frame again
    assert [(u.speaker, u.text) for u in t.utterances] == [("Casey", "Nereye gidiyorsun?")]
    # A draft replaced by the final translation: the same line, new words.
    assert t.observe(1, "Casey", "Where are you going?", "Nereye gidiyorsun ki?", now=0.5) is True
    assert len(t) == 1 and t.utterances[0].text == "Nereye gidiyorsun ki?"


def test_a_reveal_or_a_corrected_reading_replaces_the_line() -> None:
    t = Transcript()
    t.observe(1, "Alan", "It's like they're", "Sanki onlar", now=0.0)
    t.observe(1, "Alan", "It's like they're coming in over a bad signal.", "Sanki sinyal kötü.", now=0.3)  # typewriter
    assert [u.text for u in t.utterances] == ["Sanki sinyal kötü."]
    t.observe(1, "Alan", "It's Iike they're coming in over a bad signal.", "Sanki sinyal kötüymüş.", now=0.6)  # OCR l/I
    assert [u.text for u in t.utterances] == ["Sanki sinyal kötüymüş."]


def test_the_next_line_at_the_same_spot_is_a_new_utterance() -> None:
    t = Transcript()
    t.observe(1, "Casey", "I followed you.", "Seni takip ettim.", now=0.0)
    t.observe(1, "Alan", "The Dark Place bleeds through.", "Karanlık Yer sızıyor.", now=2.0)  # block 1 reused
    assert [(u.speaker, u.text) for u in t.utterances] == [
        ("Casey", "Seni takip ettim."),
        ("Alan", "Karanlık Yer sızıyor."),
    ]


def test_a_line_lost_and_found_again_is_not_doubled() -> None:
    t = Transcript()
    t.observe(1, "Casey", "Stay close.", "Yakın dur.", now=0.0)
    assert t.observe(2, "Casey", "Stay close.", "Yakın dur.", now=1.0) is False  # a new block, the same text
    assert len(t) == 1 and t.utterances[0].block_id == 2  # and it goes on following the new block
    t.observe(3, "Casey", "Stay close.", "Yakın dur.", now=9.0)  # said again much later: a second time
    assert len(t) == 2


def test_lines_are_capped_and_age_out() -> None:
    t = Transcript(lines=2, seconds=10)
    for i, text in enumerate(["one", "two", "three"]):
        t.observe(i, "", text, text.upper(), now=float(i))
    assert [u.text for u in t.utterances] == ["TWO", "THREE"]  # the oldest fell off the card
    assert t.prune(now=11.5) is True  # "two" was said at 1.0: gone after ten seconds
    assert [u.text for u in t.utterances] == ["THREE"]
    assert t.prune(now=11.6) is False
    t.seconds = 0
    assert t.prune(now=1000.0) is False  # never
    t.lines = 1
    t.observe(9, "", "four", "FOUR", now=12.0)
    assert [u.text for u in t.utterances] == ["FOUR"]


def test_speakers_are_numbered_as_they_first_speak() -> None:
    t = Transcript()
    t.observe(1, "Casey", "a", "A", now=0.0)
    t.observe(2, "Alan", "b", "B", now=1.0)
    t.observe(3, "", "c", "C", now=2.0)
    t.observe(4, "Casey", "d", "D", now=3.0)
    assert [t.speaker_index(u.speaker) for u in t.utterances] == [0, 1, -1, 0]
    t.clear()
    assert len(t) == 0 and t.speaker_index("Alan") == 1  # colours survive a clear
