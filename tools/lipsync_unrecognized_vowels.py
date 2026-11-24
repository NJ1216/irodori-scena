"""Keep isolated single-vowel mouth shapes when phonetic evidence is absent."""
import numpy as np

from evaluate_japanese_lipsync import TICKS, VOWELS, merge


def isolated_ranges(rows):
    """Consider short utterances separated by actual pauses, not arbitrary crops."""
    islands, current = [], []
    for row in rows:
        if row[2] == 'pau' and row[1] - row[0] >= 1_200_000:
            if current:
                islands.append(current)
            current = []
        else:
            current.append(row)
    if current:
        islands.append(current)
    for island in islands:
        labels = {label for _, _, label in island if label in VOWELS}
        voiced = sum(b - a for a, b, label in island if label in VOWELS)
        if (len(labels) == 1 and 1_200_000 <= voiced
                and island[-1][1] - island[0][0] <= TICKS):
            yield island, next(iter(labels))


def retry_supported(audio, rate, start, end, recognizer):
    """Either strong contextual recognition prevents fallback; failures do too."""
    duration = len(audio) / rate
    for padding in (.2, .4):
        left, right = max(0, start - padding), min(duration, end + padding)
        prefix = .4 if left == 0 and padding == .4 else 0
        samples = audio[round(left * rate):round(right * rate)]
        if prefix:
            samples = np.concatenate((np.zeros(round(prefix * rate), dtype=audio.dtype), samples))
        try:
            events, _ = recognizer(samples, rate)
        except Exception:
            return True
        if any(e['phone'].lower() in VOWELS and e['confidence'] >= .95
               and start <= e['time'] + left - prefix < end for e in events):
            return True
    return False


def preserve_unrecognized_vowels(original, candidate, events, audio, rate, recognizer):
    """Fallback to runtime Rhubarb input, never a saved completed LAB or text."""
    result, changes = list(candidate), []
    for island, vowel in isolated_ranges(original):
        left, right = island[0][0], island[-1][1]
        if not any(a < right and b > left and label in VOWELS and label != vowel
                   for a, b, label in result):
            continue
        if any(left / TICKS <= e['time'] < right / TICKS
               and e['phone'].lower() in VOWELS and e['confidence'] >= .95 for e in events):
            continue
        if retry_supported(audio, rate, left / TICKS, right / TICKS, recognizer):
            continue
        cuts = sorted({t for a, b, _ in (*result, *island) for t in (a, b)})
        restored = []
        index = 0
        for a, b in zip(cuts, cuts[1:]):
            while result[index][1] <= a:
                index += 1
            label = result[index][2]
            source = next((label for start, end, label in island if start <= a < end), None)
            if source is not None and label != 'pau':
                label = source
            restored.append((a, b, label))
        result = merge(restored)
        changes.append({'start': left, 'end': right, 'vowel': vowel,
                        'reason': 'no_supported_phonetic_vowel'})
    return result, changes
