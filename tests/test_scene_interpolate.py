import pytest
from aether.scenes.interpolate import interpolate_stops


def test_single_stop_all_segments_same():
    stops = [[0, [255, 0, 0]]]
    result = interpolate_stops(stops, segment_count=22)
    assert len(result) == 22
    for i in range(22):
        assert result[i] == (255, 0, 0)


def test_two_stops_linear_gradient():
    stops = [[0, [0, 0, 0]], [21, [210, 210, 210]]]
    result = interpolate_stops(stops, segment_count=22)
    assert result[0] == (0, 0, 0)
    assert result[21] == (210, 210, 210)
    r, g, b = result[10]
    assert 95 <= r <= 105


def test_three_stops_piecewise():
    stops = [[0, [255, 0, 0]], [10, [0, 255, 0]], [21, [0, 0, 255]]]
    result = interpolate_stops(stops, segment_count=22)
    assert result[0] == (255, 0, 0)
    assert result[10] == (0, 255, 0)
    assert result[21] == (0, 0, 255)
    r, g, b = result[5]
    assert 120 <= r <= 135
    assert 120 <= g <= 135


def test_two_stops_not_at_endpoints():
    stops = [[3, [100, 100, 100]], [18, [200, 200, 200]]]
    result = interpolate_stops(stops, segment_count=22)
    assert result[0] == (100, 100, 100)
    assert result[2] == (100, 100, 100)
    assert result[19] == (200, 200, 200)
    assert result[21] == (200, 200, 200)
    assert result[3] == (100, 100, 100)
    assert result[18] == (200, 200, 200)


def test_deep_space_star_pattern():
    stops = [
        [0, [5, 5, 40]],
        [7, [200, 200, 255]],
        [10, [5, 5, 40]],
        [18, [150, 150, 220]],
        [21, [5, 5, 40]],
    ]
    result = interpolate_stops(stops, segment_count=22)
    assert len(result) == 22
    assert result[0] == (5, 5, 40)
    assert result[7] == (200, 200, 255)
    assert result[10] == (5, 5, 40)
    assert result[18] == (150, 150, 220)
    assert result[21] == (5, 5, 40)


def test_single_segment_device():
    stops = [[0, [180, 140, 60]]]
    result = interpolate_stops(stops, segment_count=1)
    assert len(result) == 1
    assert result[0] == (180, 140, 60)
