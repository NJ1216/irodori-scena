"""Fixed comparison inputs, independent of generated preview pages."""
import json


def review_inputs(source, review, include_review):
    inputs = []
    for number in ("079", "122", "143"):
        wav = next(source.glob(number + "_*.wav"))
        inputs.append((number, "audit_" + wav.stem, wav,
                       wav.with_suffix(".txt").read_text(encoding="utf-8-sig").strip(), None))
    if include_review:
        texts = json.loads((review / "review-texts.json").read_text(encoding="utf-8"))
        data = json.loads((review / "review-data.json").read_text(encoding="utf-8"))
        for stem, variants in data.items():
            inputs.append((stem, stem, review / "media" / (stem + ".wav"), texts[stem],
                           [tuple(row) for row in variants["baseline"]]))
    return inputs
