"""The speaker split: the name a game prints before a line, with a colon or
on a line of its own, comes off so the words alone are translated; labels
and wrapped sentences stay whole."""

from __future__ import annotations

from gametl.textutil import split_speaker


def test_split_speaker() -> None:
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
    assert split_speaker('Saga Anderson\n"We\'re close."') == ("Saga Anderson", '"We\'re close."')
    assert split_speaker("Alan\nCasey... and the stairs were gone.") == ("Alan", "Casey... and the stairs were gone.")
    # A sentence wrapped after its first word, a name that is the whole line, a lead-in: not speakers.
    assert split_speaker("The\nfire escape was gone.") == ("", "The\nfire escape was gone.")
    assert split_speaker("Casey") == ("", "Casey")
    assert split_speaker("Wait.\nDon't go.") == ("", "Wait.\nDon't go.")  # a short sentence, not a name
    assert split_speaker("Mr. Wake.\nYou're late.") == ("", "Mr. Wake.\nYou're late.")
    assert split_speaker("Warning\nLow health") == ("", "Warning\nLow health")
    assert split_speaker("Where are you going?") == ("", "Where are you going?")
