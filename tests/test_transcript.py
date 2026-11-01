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
    assert split_speaker("Objective: Find the key") == ("", "Objective: Find the key")  # a lead-in, not a name
    assert split_speaker("Warning: Low health") == ("", "Warning: Low health")
    assert split_speaker("The Dark Place Manuscript: page 3") == ("", "The Dark Place Manuscript: page 3")
    assert split_speaker("Casey:") == ("", "Casey:")
    # The name on a line of its own above the words, no colon, as Alan Wake 2 prints it.
    assert split_speaker("Casey\nAnd you didn't deserve it.") == ("Casey", "And you didn't deserve it.")
    assert split_speaker("THORNTON\nLet the day shift handle it.") == ("THORNTON", "Let the day shift handle it.")
    assert split_speaker("Saga Anderson\n\"We're close.\"") == ("Saga Anderson", "\"We're close.\"")
    assert split_speaker("Alan\nCasey... and the stairs were gone.") == ("Alan", "Casey... and the stairs were gone.")
    # A sentence wrapped after its first word, a name that is the whole line, a lead-in: not speakers.
    assert split_speaker("The\nfire escape was gone.") == ("", "The\nfire escape was gone.")
    assert split_speaker("Casey") == ("", "Casey")
    assert split_speaker("Warning\nLow health") == ("", "Warning\nLow health")
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
    for now in (0.1, 0.2, 7.0):  # on screen for seven seconds
        t.observe(1, "Casey", "Stay close.", "Yakın dur.", now=now)
    assert t.observe(2, "Casey", "Stay close.", "Yakın dur.", now=8.0) is False  # a new block, the same text
    assert len(t) == 1 and t.utterances[0].block_id == 2  # and it goes on following the new block
    t.observe(3, "Casey", "Stay close.", "Yakın dur.", now=16.0)  # said again much later: a second time
    assert len(t) == 2


def test_the_same_words_from_another_speaker_are_another_line() -> None:
    t = Transcript()
    t.observe(1, "Casey", "What?", "Ne?", now=0.0)
    t.observe(1, "Alan", "What?", "Ne?", now=1.0)  # the tracker reused block 1
    t.observe(2, "ALAN", "What?", "Ne?", now=1.5)  # OCR read the name in capitals: the same Alan
    assert [(u.speaker, u.block_id) for u in t.utterances] == [("Casey", 1), ("ALAN", 2)]
    assert t.speaker_index("Alan") == t.speaker_index("ALAN") == 1


def test_a_reveal_after_an_ocr_slip_is_still_one_line() -> None:
    t = Transcript()
    t.observe(1, "Alan", "It's like they'n", "Sanki onlar", now=0.0)
    t.observe(1, "Alan", "It's like they're coming in over a bad signal.", "Sanki sinyal kötü.", now=0.4)
    assert [u.text for u in t.utterances] == ["Sanki sinyal kötü."]


def test_lines_age_out_after_they_were_last_seen_and_are_capped() -> None:
    t = Transcript(lines=2, seconds=10)
    for i, text in enumerate(["one", "two", "three"]):
        t.observe(i, "", text, text.upper(), now=float(i))
    assert [u.text for u in t.utterances] == ["TWO", "THREE"]  # the oldest fell off the card
    t.observe(2, "", "three", "THREE", now=11.0)  # "three" is still on screen
    assert t.prune(now=11.5) is True  # "two" was last seen at 1.0: gone after ten seconds
    assert [u.text for u in t.utterances] == ["THREE"]
    assert t.prune(now=20.0) is False  # "three" was seen at 11.0: it stays
    assert t.observe(2, "", "three", "THREE", now=30.0) is False
    assert t.prune(now=41.0) is True and len(t) == 0  # gone ten seconds after its last sighting
    # Still on screen after its time on the card: not said again.
    assert t.observe(2, "", "three", "THREE", now=41.5) is False and len(t) == 0
    assert t.observe(2, "", "four", "FOUR", now=42.0) is True  # the next line at that spot is new
    t.seconds = 0
    assert t.prune(now=1000.0) is False  # never
    t.observe(3, "", "five", "FIVE", now=43.0)
    t.lines = 1
    assert t.prune(now=43.0) is True  # fewer lines kept: the oldest go at once
    assert [u.text for u in t.utterances] == ["FIVE"]


def test_forgotten_blocks_are_found_again_by_their_words() -> None:
    t = Transcript()
    t.observe(1, "Casey", "Stay close.", "Yakın dur.", now=0.0)
    t.observe(2, "Alan", "Go.", "Git.", now=1.0)
    t.forget_blocks()  # a rescan: the tracker numbers afresh
    assert t.observe(1, "Alan", "Go.", "Git.", now=1.2) is False  # block 1 is now Alan's line
    assert t.observe(2, "Casey", "Stay close.", "Yakın dur.", now=1.3) is False
    assert [(u.speaker, u.block_id) for u in t.utterances] == [("Casey", 2), ("Alan", 1)]


def test_speakers_are_numbered_as_they_first_speak() -> None:
    t = Transcript()
    t.observe(1, "Casey", "a", "A", now=0.0)
    t.observe(2, "Alan", "b", "B", now=1.0)
    t.observe(3, "", "c", "C", now=2.0)
    t.observe(4, "Casey", "d", "D", now=3.0)
    assert [t.speaker_index(u.speaker) for u in t.utterances] == [0, 1, -1, 0]
    t.clear()
    assert len(t) == 0 and t.speaker_index("Alan") == 1  # colours survive a clear
    assert t.observe(1, "Casey", "a", "A", now=5.0) is True  # and the lines taken before do not hold it back
