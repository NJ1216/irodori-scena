"""Temporal smoothing for offline acoustic LAB experiments only."""

VOWELS = frozenset(("a", "i", "u", "e", "o"))


def bridge_uncertain_frames(observations, max_gap=6):
    """Bridge <=120ms unknown gaps only when both ends agree on a vowel."""
    result = list(observations)
    index = 0
    while index < len(result):
        if result[index] is not None:
            index += 1
            continue
        end = index + 1
        while end < len(result) and result[end] is None:
            end += 1
        before = result[index - 1] if index else None
        after = result[end] if end < len(result) else None
        if end - index <= max_gap and before in VOWELS and before == after:
            result[index:end] = [before] * (end - index)
        index = end
    return result


def suppress_short_vowels(rows, minimum_ticks=600_000, protected=()):
    """Absorb <60ms vowel excursions; never cross silence or closed lips.

    Use the longer neighboring vowel when they disagree. Boundary intervals
    without a vowel neighbor remain intact, preserving brief isolated speech.
    """
    result = list(rows)
    while True:
        candidates = []
        for index, (start, end, label) in enumerate(result):
            if (label not in VOWELS or end - start >= minimum_ticks
                    or any(a < end and b > start and shape == label for a, b, shape in protected)):
                continue
            neighbors = [other for other in (index - 1, index + 1)
                         if 0 <= other < len(result) and result[other][2] in VOWELS]
            if neighbors:
                candidates.append((end - start, index, neighbors))
        if not candidates:
            return result
        _, index, neighbors = min(candidates)
        neighbor = max(neighbors, key=lambda other: result[other][1] - result[other][0])
        start, end, _ = result[index]
        result[index] = (start, end, result[neighbor][2])
        merged = []
        for start, end, label in result:
            if merged and merged[-1][2] == label:
                merged[-1] = (merged[-1][0], end, label)
            else:
                merged.append((start, end, label))
        result = merged
