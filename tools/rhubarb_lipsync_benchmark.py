"""Core helpers for the standalone Rhubarb lip-sync suitability benchmark."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TICKS_PER_SECOND = 10_000_000
SHAPE_TO_LAB = {"A": "N", "B": "i", "C": "e", "D": "a", "E": "o", "F": "u", "X": "pau"}
CATEGORY_QUOTAS = {
    "ordinary": 8,
    "sibilants": 4,
    "closed_mouth": 4,
    "laughter_repetition": 5,
    "emoji_nonverbal": 5,
    "long_pause": 4,
}
SIBILANTS = re.compile(r"[さしすせそざじずぜぞサシスセソザジズゼゾ]")
CLOSED_MOUTH = re.compile(r"[まみむめもばびぶべぼぱぴぷぺぽマミムメモバビブベボパピプペポ]")
LAUGHTER = re.compile(r"(?:はは|ハハ|ふふ|フフ|へへ|ヘヘ|あは|アハ|笑|ｗｗ|ww)", re.IGNORECASE)
REPETITION = re.compile(r"([ぁ-んァ-ンー]{1,4})(?:[、, ]*)\1")
NONVERBAL = re.compile(r"(?:😮‍💨|🥱|😴|🤧|🌬️?|ため息|吐息|あくび|くしゃみ|咳|ふぅ|はぁ)")
LONG_PAUSE = re.compile(r"(?:…{2,}|・{3,})")


@dataclass(frozen=True)
class Sample:
    category: str
    line_id: str
    take_id: str
    text: str
    wav: Path

    @property
    def key(self) -> str:
        return f"{self.line_id}__{self.take_id}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as source:
        if source.getframerate() <= 0:
            raise ValueError(f"WAV has an invalid sample rate: {path.name}")
        return source.getnframes() / source.getframerate()


def _matches(category: str, text: str) -> bool:
    if category == "sibilants":
        return bool(SIBILANTS.search(text))
    if category == "closed_mouth":
        return bool(CLOSED_MOUTH.search(text))
    if category == "laughter_repetition":
        return bool(LAUGHTER.search(text) or REPETITION.search(text))
    if category == "emoji_nonverbal":
        return bool(NONVERBAL.search(text))
    if category == "long_pause":
        return bool(LONG_PAUSE.search(text) or len(re.findall(r"[、。！？!?]", text)) >= 3)
    return not any(_matches(name, text) for name in ("laughter_repetition", "emoji_nonverbal", "long_pause"))


def load_selected_takes(project_dir: Path) -> list[Sample]:
    project_file = project_dir / "project.json"
    if not project_file.is_file():
        raise ValueError(f".scena project.json not found: {project_file}")
    project = json.loads(project_file.read_text(encoding="utf-8"))
    candidates: list[Sample] = []
    for scene in project.get("scenes", []):
        for line in scene.get("lines", []):
            selected_id = line.get("selectedTakeId")
            take = next((item for item in line.get("takes", []) if item.get("id") == selected_id), None)
            if not take:
                continue
            audio_url = str(take.get("audioUrl", ""))
            if not audio_url.startswith("/media/") or ".." in Path(audio_url).parts:
                continue
            wav = (project_dir / "media" / audio_url.removeprefix("/media/")).resolve()
            try:
                wav.relative_to((project_dir / "media").resolve())
            except ValueError:
                continue
            if not wav.is_file():
                continue
            text = str(take.get("renderedText") or line.get("text") or "")
            candidates.append(Sample("", str(line.get("id", "")), str(selected_id), text, wav))
    return candidates


def select_corpus(candidates: list[Sample]) -> list[Sample]:
    """Fill fixed, non-overlapping quotas with stable hash ordering."""
    chosen: list[Sample] = []
    used: set[str] = set()
    order = ("laughter_repetition", "emoji_nonverbal", "long_pause", "sibilants", "closed_mouth", "ordinary")
    ranked = sorted(candidates, key=lambda item: hashlib.sha256(item.key.encode()).hexdigest())
    for category in order:
        matching = [item for item in ranked if item.key not in used and _matches(category, item.text)]
        need = CATEGORY_QUOTAS[category]
        if len(matching) < need:
            raise ValueError(f"Category {category} needs {need} unique selected takes, but only {len(matching)} are available.")
        for item in matching[:need]:
            chosen.append(Sample(category, item.line_id, item.take_id, item.text, item.wav))
            used.add(item.key)
    return sorted(chosen, key=lambda item: (list(CATEGORY_QUOTAS).index(item.category), item.key))


def parse_mouth_cues(payload: dict[str, Any]) -> list[tuple[float, float, str]]:
    raw = payload.get("mouthCues")
    if not isinstance(raw, list):
        raise ValueError("Rhubarb JSON does not contain mouthCues.")
    cues: list[tuple[float, float, str]] = []
    previous_end = 0.0
    for index, cue in enumerate(raw):
        if not isinstance(cue, dict):
            raise ValueError(f"mouthCues[{index}] is not an object.")
        start, end, shape = cue.get("start"), cue.get("end"), cue.get("value")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise ValueError(f"mouthCues[{index}] has invalid boundaries.")
        start, end = float(start), float(end)
        if not math.isfinite(start) or not math.isfinite(end) or start < previous_end or end <= start:
            raise ValueError(f"mouthCues[{index}] is not positive, ordered, and non-overlapping.")
        if shape not in SHAPE_TO_LAB:
            raise ValueError(f"mouthCues[{index}] has unsupported shape {shape!r}.")
        cues.append((start, end, str(shape)))
        previous_end = end
    return cues


def cues_to_lab(cues: list[tuple[float, float, str]], duration: float) -> list[tuple[int, int, str]]:
    duration_ticks = round(duration * TICKS_PER_SECOND)
    if duration_ticks <= 0:
        raise ValueError("WAV duration must be positive.")
    intervals: list[tuple[int, int, str]] = []
    cursor = 0
    for start, end, shape in cues:
        start_tick = min(duration_ticks, max(0, round(start * TICKS_PER_SECOND)))
        end_tick = min(duration_ticks, max(0, round(end * TICKS_PER_SECOND)))
        if start_tick > cursor:
            intervals.append((cursor, start_tick, "pau"))
        if end_tick > max(cursor, start_tick):
            intervals.append((max(cursor, start_tick), end_tick, SHAPE_TO_LAB[shape]))
            cursor = end_tick
        if cursor >= duration_ticks:
            break
    if cursor < duration_ticks:
        intervals.append((cursor, duration_ticks, "pau"))
    merged: list[tuple[int, int, str]] = []
    for start, end, label in intervals:
        if end <= start:
            continue
        if merged and merged[-1][2] == label:
            merged[-1] = (merged[-1][0], end, label)
        else:
            merged.append((start, end, label))
    validate_lab(merged, duration_ticks)
    return merged


def validate_lab(rows: list[tuple[int, int, str]], duration_ticks: int) -> None:
    if not rows or rows[0][0] != 0 or rows[-1][1] != duration_ticks:
        raise ValueError("LAB does not cover the entire WAV.")
    cursor = 0
    for start, end, label in rows:
        if start != cursor or end <= start or label not in set(SHAPE_TO_LAB.values()):
            raise ValueError("LAB is not positive, ordered, and continuous.")
        cursor = end


def lab_text(rows: list[tuple[int, int, str]]) -> str:
    return "".join(f"{start} {end} {label}\n" for start, end, label in rows)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]


def preview_html(samples: list[Sample], records: list[dict[str, Any]]) -> str:
    cards = []
    by_key = {record["key"]: record for record in records}
    for sample in samples:
        record = by_key[sample.key]
        audio = base64.b64encode(sample.wav.read_bytes()).decode("ascii")
        labels = json.dumps(record["lab"], ensure_ascii=False).replace("</", "<\\/")
        cards.append(f'''<article data-key="{html.escape(sample.key)}"><h2>{html.escape(sample.category)} — {html.escape(sample.key)}</h2>
<div class="performance"><div class="face" aria-label="現在の口形"><span class="eye left"></span><span class="eye right"></span><span class="mouth pau"></span><b class="shape">pau</b></div>
<div class="script"><strong>台詞</strong><p>{html.escape(sample.text)}</p><p class="hint">文字位置は推定せず、Rhubarbが検出した口形だけを音声に同期して表示します。</p></div></div>
<audio controls preload="metadata" src="data:audio/wav;base64,{audio}"></audio>
<canvas width="900" height="80" data-labels='{html.escape(labels, quote=True)}' aria-label="口形タイムライン"></canvas>
<label><input type="radio" name="{html.escape(sample.key)}" value="usable">使用可能</label>
<label><input type="radio" name="{html.escape(sample.key)}" value="concern">境界が気になる</label>
<label><input type="radio" name="{html.escape(sample.key)}" value="unusable">使用不可</label></article>''')
    return """<!doctype html><meta charset=utf-8><title>Rhubarb lip-sync review</title><style>
body{font:15px system-ui;max-width:960px;margin:auto;padding:24px;color:#202124;background:#fafafa}article{border:1px solid #bbb;border-radius:12px;padding:18px;margin:18px 0;background:white}audio{width:100%;margin:12px 0}canvas{width:100%;height:80px;background:#eee;border-radius:6px}label{margin-right:20px}button{padding:8px 14px;position:sticky;top:8px;z-index:2}.performance{display:grid;grid-template-columns:180px 1fr;gap:22px;align-items:center}.face{position:relative;width:150px;height:150px;border-radius:50%;background:#ffe0bd;border:3px solid #47362e;margin:auto}.eye{position:absolute;top:48px;width:12px;height:18px;border-radius:50%;background:#33251f}.eye.left{left:40px}.eye.right{right:40px}.mouth{position:absolute;left:50%;top:96px;transform:translate(-50%,-50%);box-sizing:border-box;background:#8d2942;border:3px solid #5e1d2d;transition:width 70ms,height 70ms,border-radius 70ms}.mouth.pau{width:32px;height:4px;border:0;border-radius:2px}.mouth.N{width:42px;height:5px;border-radius:50%}.mouth.i{width:72px;height:16px;border-radius:45%}.mouth.e{width:62px;height:28px;border-radius:45%}.mouth.a{width:52px;height:55px;border-radius:48%}.mouth.o{width:43px;height:43px;border-radius:50%}.mouth.u{width:27px;height:34px;border-radius:50%}.shape{position:absolute;left:0;right:0;bottom:6px;text-align:center;font-size:13px}.script p{font-size:18px;line-height:1.8}.script .hint{font-size:12px;color:#666}@media(max-width:600px){.performance{grid-template-columns:1fr}.face{width:120px;height:120px}.eye{top:37px}.mouth{top:76px}}</style>
<h1>PSDToolKit互換口形LAB 評価</h1><p>口形近似であり、音素LAB・学習ラベルではありません。</p><button id=save>評価JSONを保存</button>""" + "".join(cards) + """<script>
const store='scena-rhubarb-review';let reviews=JSON.parse(localStorage.getItem(store)||'{}');
document.querySelectorAll('input').forEach(x=>{x.checked=reviews[x.name]===x.value;x.onchange=()=>{reviews[x.name]=x.value;localStorage.setItem(store,JSON.stringify(reviews))}});
document.querySelectorAll('article').forEach(card=>{let audio=card.querySelector('audio'),c=card.querySelector('canvas'),x=c.getContext('2d'),a=JSON.parse(c.dataset.labels),end=a.at(-1)[1],mouth=card.querySelector('.mouth'),shape=card.querySelector('.shape'),frame=0;
function draw(){x.clearRect(0,0,c.width,c.height);a.forEach((r,i)=>{let l=r[0]/end*c.width,w=(r[1]-r[0])/end*c.width;x.fillStyle=`hsl(${i%7*47} 55% 72%)`;x.fillRect(l,0,w,c.height);x.fillStyle='#111';x.fillText(r[2],l+3,44)});let tick=audio.currentTime*10000000,current=a.find(r=>tick>=r[0]&&tick<r[1])||a.at(-1),px=Math.min(c.width,tick/end*c.width);mouth.className='mouth '+current[2];shape.textContent=current[2];x.fillStyle='#d71920';x.fillRect(px,0,3,c.height)}
function animate(){draw();if(!audio.paused&&!audio.ended)frame=requestAnimationFrame(animate)}audio.onplay=()=>{cancelAnimationFrame(frame);animate()};audio.onpause=draw;audio.onseeked=draw;audio.onended=draw;draw()});
save.onclick=()=>{let b=new Blob([JSON.stringify({reviews},null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='review.json';a.click();URL.revokeObjectURL(a.href)};
</script>"""


def markdown_scorecard(summary: dict[str, Any]) -> str:
    lines = [
        "# Rhubarb Lip Sync 評価票", "", "> PSDToolKit互換の口形近似LABです。音素LABではありません。", "",
        "## 自動ゲート", "", f"- 判定: **{'PASS' if summary['automaticPass'] else 'FAIL'}**",
        f"- 成功件数: {summary['successfulCount']} / 30", f"- warm p95 RTF: {summary['warmP95Rtf']}",
        f"- 3回決定性（観測値・キャッシュで固定）: {'同一' if summary['deterministic'] else '差異あり'}", "", "## 聴覚・視覚評価", "",
        "`preview.html` で評価し、保存した `review.json` を証跡として保管してください。", "",
        "- [ ] 全体の使用可能が80%以上", "- [ ] 各カテゴリの使用可能が70%以上",
        "- [ ] 笑い・息で無音固定や不自然な高速切替が継続しない", "", "## Windows / PSDToolKit 最終ゲート", "",
        "- [ ] 代表10件すべてが解析エラーなく読み込める", "- [ ] 8件以上が修正不要で使用可能", "",
        "いずれかを満たさない場合はSCENAへ統合しない。", "",
    ]
    return "\n".join(lines)
