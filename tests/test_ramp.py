from aether.lighting.ramp import ColorState, interpolate, generate_ramp


def test_interpolate_midpoint():
    start = ColorState(r=0, g=0, b=0, brightness=0)
    end = ColorState(r=100, g=200, b=50, brightness=100)
    mid = interpolate(start, end, 0.5)
    assert mid.r == 50
    assert mid.g == 100
    assert mid.b == 25
    assert mid.brightness == 50


def test_interpolate_start():
    start = ColorState(r=255, g=0, b=0, brightness=80)
    end = ColorState(r=0, g=255, b=0, brightness=20)
    result = interpolate(start, end, 0.0)
    assert result == start


def test_interpolate_end():
    start = ColorState(r=255, g=0, b=0, brightness=80)
    end = ColorState(r=0, g=255, b=0, brightness=20)
    result = interpolate(start, end, 1.0)
    assert result == end


def test_generate_ramp_step_count():
    start = ColorState(r=0, g=0, b=0, brightness=0)
    end = ColorState(r=255, g=255, b=255, brightness=100)
    steps = list(generate_ramp(start, end, duration_sec=8, interval_ms=100))
    assert len(steps) == 80


def test_generate_ramp_first_and_last():
    start = ColorState(r=0, g=0, b=0, brightness=0)
    end = ColorState(r=200, g=200, b=200, brightness=100)
    steps = list(generate_ramp(start, end, duration_sec=2, interval_ms=100))
    assert steps[0].brightness < 10
    assert steps[-1].brightness >= 95


def test_color_state_to_dict():
    cs = ColorState(r=255, g=180, b=60, brightness=80)
    d = cs.to_dict()
    assert d == {"r": 255, "g": 180, "b": 60, "brightness": 80}
