from aether.vox.intent import classify_intent, Intent


def test_exact_keyword_focus():
    assert classify_intent("focus") == Intent.MODE_FOCUS

def test_exact_keyword_party():
    assert classify_intent("party") == Intent.MODE_PARTY

def test_exact_keyword_sleep():
    assert classify_intent("sleep") == Intent.MODE_SLEEP

def test_keyword_goodnight():
    assert classify_intent("goodnight") == Intent.MODE_SLEEP

def test_stop_focus():
    assert classify_intent("stop focus") == Intent.MODE_FOCUS_STOP

def test_end_focus():
    assert classify_intent("end focus") == Intent.MODE_FOCUS_STOP

def test_stop_party():
    assert classify_intent("stop party") == Intent.MODE_PARTY_STOP

def test_generic_stop():
    assert classify_intent("stop") == Intent.MODE_STOP

def test_generic_cancel():
    assert classify_intent("cancel") == Intent.MODE_STOP

def test_pause():
    assert classify_intent("pause") == Intent.PAUSE

def test_resume():
    assert classify_intent("resume") == Intent.RESUME

def test_unpause():
    assert classify_intent("unpause") == Intent.RESUME

def test_brighter():
    assert classify_intent("brighter") == Intent.BRIGHTNESS_UP

def test_dimmer():
    assert classify_intent("dimmer") == Intent.BRIGHTNESS_DOWN

def test_warmer():
    assert classify_intent("warmer") == Intent.COLOR_WARMER

def test_cooler():
    assert classify_intent("cooler") == Intent.COLOR_COOLER

def test_lights_off():
    assert classify_intent("lights off") == Intent.LIGHTS_OFF

def test_lights_on():
    assert classify_intent("lights on") == Intent.LIGHTS_ON

def test_case_insensitive():
    assert classify_intent("BRIGHTER") == Intent.BRIGHTNESS_UP

def test_substring_match():
    assert classify_intent("can you make it brighter") == Intent.BRIGHTNESS_UP

def test_multiword_before_single():
    assert classify_intent("stop focus") == Intent.MODE_FOCUS_STOP

def test_unknown_returns_none():
    assert classify_intent("what time is it") is None

def test_party_mode_synonym():
    assert classify_intent("party mode") == Intent.MODE_PARTY
