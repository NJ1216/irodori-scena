#!/usr/bin/env python3
"""Build an offline anonymous two-column review page from benchmark reports."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any


CRITERIA = ("自然さ", "物語展開", "人物一貫性", "重複の少なさ", "演出品質", "総合選好")


def _lines(report: dict[str, Any]) -> list[dict[str, str]]:
    scenes = report.get("savedProject", {}).get("scenes", [])
    return [line for scene in scenes if scene.get("lines") for line in scene["lines"]]


def _script(report: dict[str, Any]) -> str:
    names = {str(item.get("id")): str(item.get("name"))
             for item in report.get("savedProject", {}).get("characters", [])}
    rows = []
    for line in _lines(report):
        speaker = html.escape(names.get(str(line.get("characterId")), "話者"))
        direction = html.escape(str(line.get("stageDirection", "")))
        text = html.escape(str(line.get("text", "")))
        rows.append(f'<article class="line"><header>{speaker}</header><p>{text}</p>'
                    f'<small>{direction}</small></article>')
    return "".join(rows)


def _order(label: str, reports: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    digest = hashlib.sha256(f"{seed}:{label}".encode()).digest()
    return reports if digest[0] % 2 == 0 else list(reversed(reports))


def build(fixtures: list[tuple[str, Path, Path]], output: Path, seed: int) -> None:
    sections, key = [], {}
    for label, baseline_path, adaptive_path in fixtures:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        adaptive = json.loads(adaptive_path.read_text(encoding="utf-8"))
        if baseline.get("theme") != adaptive.get("theme"):
            raise ValueError(f"{label}: paired reports do not contain the same theme")
        ordered = _order(label, [baseline, adaptive], seed)
        key[label] = {"A": ordered[0]["variant"], "B": ordered[1]["variant"]}
        choices = "".join(
            f'<fieldset><legend>{criterion}</legend>'
            f'<label><input type="radio" name="{label}-{index}" value="A">A</label>'
            f'<label><input type="radio" name="{label}-{index}" value="tie">同等</label>'
            f'<label><input type="radio" name="{label}-{index}" value="B">B</label></fieldset>'
            for index, criterion in enumerate(CRITERIA)
        )
        theme = html.escape(str(baseline.get("theme", "")))
        sections.append(f'<section data-fixture="{html.escape(label)}"><h2>{html.escape(label)}</h2>'
                        f'<div class="theme"><strong>共通テーマ</strong><p>{theme}</p></div>'
                        f'<div class="columns"><div><h3>台本 A</h3>{_script(ordered[0])}</div>'
                        f'<div><h3>台本 B</h3>{_script(ordered[1])}</div></div>'
                        f'<div class="score">{choices}<label>所見<textarea name="{label}-notes"></textarea></label></div></section>')
    page = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>台本盲検評価</title><style>
:root{{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;color:#25231f;background:#f4f1e9}}
body{{margin:0;padding:24px;line-height:1.65}}main{{max-width:1500px;margin:auto}}section{{display:none;margin:0 0 40px}}section.active{{display:block}}
.nav{{display:flex;gap:8px;margin-bottom:18px}}.theme,.columns>div,.score{{background:white;border:1px solid #d7d0c2;border-radius:12px;padding:18px}}.theme{{margin-bottom:16px}}
.columns{{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}}.columns>div{{max-height:62vh;overflow:auto}}
.line{{padding:10px 0;border-top:1px solid #eee8dc}}.line:first-of-type{{border-top:0}}.line header{{font-weight:700}}.line p{{margin:3px 0}}.line small{{color:#686158}}
.score{{margin-top:16px;display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}fieldset{{border:0;padding:0;margin:0}}legend{{font-weight:700}}label{{margin-right:14px}}textarea{{display:block;width:100%;min-height:70px;box-sizing:border-box}}
button{{padding:10px 18px}}@media(max-width:800px){{.columns,.score{{grid-template-columns:1fr}}}}</style></head>
<body><main><h1>台本盲検評価</h1><p>数値情報と生成方式は伏せています。各項目でA、同等、Bを選んでください。</p>
<nav class="nav">{''.join(f'<button type="button" data-show="{html.escape(label)}">{html.escape(label)}</button>' for label, *_ in fixtures)}</nav>
<form id="review">{''.join(sections)}<button type="button" id="export">評価JSONを保存</button></form></main>
<script>const f=document.querySelector('#review');const storage='scena-draft-blind-review';
const sections=[...f.querySelectorAll('section')];function show(label){{for(const s of sections)s.classList.toggle('active',s.dataset.fixture===label)}};for(const b of document.querySelectorAll('[data-show]'))b.onclick=()=>show(b.dataset.show);if(sections[0])sections[0].classList.add('active');
const restore=JSON.parse(localStorage.getItem(storage)||'{{}}');for(const e of f.elements){{if(!e.name)continue;if(e.type==='radio')e.checked=restore[e.name]===e.value;else e.value=restore[e.name]||''}}
f.addEventListener('input',()=>{{const d={{}};for(const e of f.elements){{if(e.name&&(e.type!=='radio'||e.checked))d[e.name]=e.value}}localStorage.setItem(storage,JSON.stringify(d))}});
document.querySelector('#export').onclick=()=>{{const data={{}};for(const e of f.elements){{if(e.name&&(e.type!=='radio'||e.checked))data[e.name]=e.value}};const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{{type:'application/json'}}));a.download='blind-review.json';a.click()}};</script></body></html>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    output.with_name("blind-key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="append", nargs=3, metavar=("LABEL", "BASELINE", "ADAPTIVE"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260904)
    args = parser.parse_args()
    build([(label, Path(base), Path(candidate)) for label, base, candidate in args.fixture], args.output, args.seed)


if __name__ == "__main__":
    main()
