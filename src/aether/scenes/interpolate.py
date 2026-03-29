from __future__ import annotations


def interpolate_stops(
    stops: list[list], segment_count: int
) -> dict[int, tuple[int, int, int]]:
    if not stops:
        return {}

    parsed: list[tuple[int, tuple[int, int, int]]] = []
    for stop in stops:
        idx = stop[0]
        color = (stop[1][0], stop[1][1], stop[1][2])
        parsed.append((idx, color))

    parsed.sort(key=lambda s: s[0])

    result: dict[int, tuple[int, int, int]] = {}

    if len(parsed) == 1:
        color = parsed[0][1]
        for i in range(segment_count):
            result[i] = color
        return result

    for seg in range(segment_count):
        if seg <= parsed[0][0]:
            result[seg] = parsed[0][1]
        elif seg >= parsed[-1][0]:
            result[seg] = parsed[-1][1]
        else:
            for j in range(len(parsed) - 1):
                left_idx, left_color = parsed[j]
                right_idx, right_color = parsed[j + 1]
                if left_idx <= seg <= right_idx:
                    if left_idx == right_idx:
                        result[seg] = left_color
                    else:
                        t = (seg - left_idx) / (right_idx - left_idx)
                        r = round(left_color[0] + (right_color[0] - left_color[0]) * t)
                        g = round(left_color[1] + (right_color[1] - left_color[1]) * t)
                        b = round(left_color[2] + (right_color[2] - left_color[2]) * t)
                        result[seg] = (r, g, b)
                    break

    return result
