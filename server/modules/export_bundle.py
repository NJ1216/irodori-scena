from __future__ import annotations

import os
import re
import shutil
import unicodedata
import wave
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from server.registry import deps


UTF8_BOM = b"\xef\xbb\xbf"
MAX_FILE_BYTES = 255
INVALID_FILE_CHARS = re.compile(r"[\x00-\x1f/:]")


@dataclass(frozen=True)
class ExportLine:
    index: int
    scene: dict[str, Any]
    line: dict[str, Any]
    cast_name: str
    text: str
    base_name: str


def clean_export_text(value: str) -> str:
    return deps.strip_draft_emojis(value)


def subtitle_export_text(item: ExportLine, include_emoji: bool) -> str:
    if include_emoji:
        return str(item.line.get("text", ""))
    return item.text


def safe_file_component(value: str, fallback: str = "名称未設定") -> str:
    cleaned = INVALID_FILE_CHARS.sub("_", value).strip().rstrip(".")
    return cleaned or fallback


def truncate_file_name(base: str, extension: str, limit: int = MAX_FILE_BYTES) -> str:
    suffix = f".{extension.lstrip('.')}"
    available = limit - len(suffix.encode("utf-8"))
    result = ""
    for character in base:
        if len((result + character).encode("utf-8")) > available:
            break
        result += character
    return (result.rstrip(" .") or "名称未設定") + suffix


def normalized_file_key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def line_base_name(index: int, cast_name: str, text: str, naming: list[str]) -> str:
    values = {
        "sequence": f"{index:03d}",
        "cast": safe_file_component(cast_name.replace(" ", ""), "キャスト"),
        "text": safe_file_component(clean_export_text(text), "セリフ"),
    }
    return "_".join(values[item] for item in naming if item != "none")


def build_export_lines(project: dict[str, Any], naming: list[str]) -> list[ExportLine]:
    cast_names = {
        str(item.get("id", "")): str(item.get("name", "")).strip() or "キャスト"
        for item in project.get("characters", [])
    }
    result = []
    index = 0
    spoken_ids = {str(line.get("id", "")) for _, line in deps.export_spoken_lines(project)}
    for scene in project.get("scenes", []):
        for line in scene.get("lines", []):
            if line.get("enabled", True) is False:
                continue
            index += 1
            if str(line.get("id", "")) not in spoken_ids:
                continue
            cast_name = cast_names.get(str(line.get("characterId", "")), "キャスト")
            text = clean_export_text(str(line.get("text", "")))
            result.append(ExportLine(index, scene, line, cast_name, text, line_base_name(index, cast_name, text, naming)))
    return result


def validate_split_names(lines: list[ExportLine], formats: list[str]) -> None:
    extensions = ["txt" if item == "subtitle_txt" else item for item in formats if item != "script_txt"]
    for extension in extensions:
        names = [truncate_file_name(item.base_name, extension) for item in lines]
        keys = [normalized_file_key(item) for item in names]
        if len(keys) != len(set(keys)):
            raise ValueError("短縮・正規化後に重複するファイル名があります。命名要素を変更してください。")


def export_wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as reader:
        return reader.getnframes() / reader.getframerate()


def srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{milliseconds:03d}"


def srt_text(entries: list[tuple[str, float, float]]) -> str:
    return "\n\n".join(
        f"{index}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{text}"
        for index, (text, start, end) in enumerate(entries, 1)
    ) + "\n"


def csv_field(value: str, delimiter: str) -> str:
    if delimiter in value or "\n" in value or "\r" in value or '"' in value:
        return '"' + value.replace('"', '""') + '"'
    return value


def script_text(project: dict[str, Any], lines: list[ExportLine], delimiter: str, quote_dialogue: bool) -> str:
    used_ids = {str(item.line.get("characterId", "")) for item in lines}
    characters = [item for item in project.get("characters", []) if str(item.get("id", "")) in used_ids]
    rows = ["【タイトル】", str(project.get("title", "")).strip(), "", "【キャスト】"]
    for character in characters:
        fields = [str(character.get("name", "")).strip()]
        role = str(character.get("role", "")).strip()
        profile = str(character.get("profile", "")).strip()
        fields.extend(item for item in (role, profile) if item)
        rows.append(delimiter.join(csv_field(item, delimiter) for item in fields))
    rows.extend(("", "【発話】"))
    for item in lines:
        dialogue = f"「{item.text}」" if quote_dialogue else item.text
        fields = [f"{item.index:03d}", item.cast_name, dialogue]
        rows.append(delimiter.join(csv_field(field, delimiter) for field in fields))
    return "\n".join(rows) + "\n"


def choose_output_name(destination: Path, title: str, layout: str, formats: list[str]) -> tuple[str, Path]:
    base = safe_file_component(title, "irodori SCENA")
    number = 1
    while True:
        candidate = base if number == 1 else f"{base} {number}"
        if layout == "split":
            occupied = (destination / candidate).exists()
        else:
            extensions = ["txt" if item == "subtitle_txt" else item for item in formats if item != "script_txt"]
            paths = [destination / truncate_file_name(candidate, ext) for ext in extensions]
            if "script_txt" in formats:
                paths.append(destination / truncate_file_name(f"{candidate} 台本", "txt"))
            occupied = any(path.exists() for path in paths)
        if not occupied:
            return candidate, destination / candidate
        number += 1


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def selected_audio(item: ExportLine) -> Path:
    return deps.take_audio_path(deps.selected_take_record(item.line) or {})


def _write_labs(
    tasks: list[tuple[ExportLine, Path, Path]], job_id: str,
) -> tuple[int, list[dict[str, Any]]]:
    from server.modules.japanese_lipsync_session import export_addon_session
    with export_addon_session() as session:
        return _write_labs_with_session(tasks, job_id, session)


def _write_labs_with_session(
    tasks: list[tuple[ExportLine, Path, Path]], job_id: str, session,
) -> tuple[int, list[dict[str, Any]]]:
    workers, thread_count = deps.rhubarb_parallelism(len(tasks))

    def should_cancel() -> bool:
        return deps.export_cancel_requested(job_id)

    failures: list[dict[str, Any]] = []
    completed_count = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scena-rhubarb") as executor:
        options = {'addon_session': session} if session is not None else {}
        futures: dict[Future[str], tuple[ExportLine, Path]] = {
            executor.submit(deps.generate_rhubarb_lab, audio, should_cancel, thread_count, **options): (item, target)
            for item, audio, target in tasks
        }
        for future in as_completed(futures):
            item, target = futures[future]
            try:
                write_bytes(target, future.result().encode())
            except deps.GenerationCancelled:
                for pending in futures:
                    pending.cancel()
                raise
            except Exception as error:
                failures.append({"lineId": str(item.line.get("id", "")), "lineNumber": item.index, "reason": str(error)})
            completed_count += 1
            deps.update_export_job(
                job_id,
                alignmentCompletedLines=completed_count,
                message=f"口形LABを解析しています… {completed_count} / {len(tasks)} 行",
            )
    failures.sort(key=lambda failure: failure["lineNumber"])
    return len(tasks) - len(failures), failures


def write_split(
    staging: Path, project: dict[str, Any], lines: list[ExportLine], formats: list[str], delimiter: str,
    quote_dialogue: bool, subtitle_include_emoji: bool, job_id: str,
) -> tuple[int, list[dict[str, Any]]]:
    count = 0
    lab_tasks: list[tuple[ExportLine, Path, Path]] = []
    for item in lines:
        audio = selected_audio(item) if any(fmt in formats for fmt in ("wav", "srt", "lab")) else None
        duration = export_wav_duration(audio) if audio else 0.0
        for fmt in formats:
            if fmt == "script_txt":
                continue
            extension = "txt" if fmt == "subtitle_txt" else fmt
            target = staging / truncate_file_name(item.base_name, extension)
            if fmt == "wav":
                shutil.copy2(audio, target)
            elif fmt == "subtitle_txt":
                write_bytes(target, UTF8_BOM + (subtitle_export_text(item, subtitle_include_emoji) + "\n").encode())
            elif fmt == "srt":
                write_bytes(target, srt_text([(item.text, 0, duration)]).encode())
            elif fmt == "lab":
                lab_tasks.append((item, audio, target))
                continue
            count += 1
    lab_count, failures = _write_labs(lab_tasks, job_id) if lab_tasks else (0, [])
    count += lab_count
    if "script_txt" in formats:
        target = staging / truncate_file_name(f"{safe_file_component(str(project.get('title', '')))} 台本", "txt")
        write_bytes(target, UTF8_BOM + script_text(project, lines, delimiter, quote_dialogue).encode())
        count += 1
    return count, failures


def joined_timeline(project: dict[str, Any], lines: list[ExportLine]) -> tuple[list[tuple[Path, float]], list[tuple[str, float, float]], list[Path | None]]:
    default_gap = float(project.get("settings", {}).get("lineGap", 0.7))
    groups: list[list[ExportLine]] = []
    for item in lines:
        cue_id = str(item.line.get("cueId", ""))
        if cue_id and groups and groups[-1][0].scene is item.scene and str(groups[-1][0].line.get("cueId", "")) == cue_id:
            groups[-1].append(item)
        else:
            groups.append([item])
    inputs, entries, durations, gaps = [], [], [], []
    for group in groups:
        item = group[0]
        if len(group) > 1:
            mix = deps.render_cue_mix(item.scene, str(item.line.get("id", "")))
            audio = deps.MEDIA_ROOT / str(mix["audioUrl"]).removeprefix("/media/")
        else:
            audio = selected_audio(item)
        duration = export_wav_duration(audio)
        gap_value = deps._strict_float(item.line.get("gapSeconds"))
        gap = max(-9999.0, min(9999.0, gap_value if gap_value is not None else default_gap))
        inputs.append((audio, gap))
        durations.append(duration)
        gaps.append(gap)
    starts, effective = deps.effective_unit_starts(durations, gaps)
    inputs = [(audio, effective[index] if index < len(effective) else 0.0) for index, (audio, _gap) in enumerate(inputs)]
    entries = [
        (item.text, starts[index], starts[index] + durations[index])
        for index, group in enumerate(groups) for item in group
    ]
    overlap_files: list[Path | None] = []
    for index, gap in enumerate(effective):
        if gap < 0:
            overlap = deps.render_adjacent_overlap(project, str(groups[index][0].line.get("id", "")))
            overlap_files.append(deps.MEDIA_ROOT / str(overlap["audioUrl"]).removeprefix("/media/"))
        else:
            overlap_files.append(None)
    overlap_files.append(None)
    return inputs, entries, overlap_files


def write_joined(
    staging: Path, base: str, project: dict[str, Any], lines: list[ExportLine], formats: list[str], delimiter: str,
    quote_dialogue: bool, subtitle_include_emoji: bool,
    should_cancel: Callable[[], bool],
) -> int:
    count = 0
    needs_audio = any(fmt in formats for fmt in ("wav", "srt"))
    from server.modules.timeline_export import export_timeline, write_timeline_wav
    plan, entries = export_timeline(project, lines) if needs_audio else ({}, [])
    if "wav" in formats:
        write_timeline_wav(plan, staging / truncate_file_name(base, "wav"), should_cancel, {str(item.line["id"]) for item in lines})
        count += 1
    if "subtitle_txt" in formats:
        subtitle_lines = (subtitle_export_text(item, subtitle_include_emoji) for item in lines)
        write_bytes(staging / truncate_file_name(base, "txt"), UTF8_BOM + ("\n".join(subtitle_lines) + "\n").encode())
        count += 1
    if "srt" in formats:
        write_bytes(staging / truncate_file_name(base, "srt"), srt_text(entries).encode())
        count += 1
    if "script_txt" in formats:
        write_bytes(staging / truncate_file_name(f"{base} 台本", "txt"), UTF8_BOM + script_text(project, lines, delimiter, quote_dialogue).encode())
        count += 1
    return count


def commit_joined(staging: Path, destination: Path) -> None:
    for source in staging.iterdir():
        os.replace(source, destination / source.name)


def export_bundle(job_id: str, project: dict[str, Any], request: dict[str, Any]) -> tuple[str, int, list[dict[str, Any]]]:
    destination = Path(str(request["destinationDir"])).expanduser().resolve()
    if not destination.is_dir():
        raise ValueError("エクスポート先は存在するフォルダである必要があります。")
    layout, formats, naming = request["layout"], request["formats"], request["naming"]
    lines = build_export_lines(project, naming)
    if layout == "split":
        validate_split_names(lines, formats)
    base, final_path = choose_output_name(destination, str(project.get("title", "")), layout, formats)
    staging = destination / f".{base}.scena-export-{job_id}"
    staging.mkdir(mode=0o700)
    try:
        writer = write_split if layout == "split" else write_joined
        if layout == "split":
            count, failures = writer(staging, project, lines, formats, request["scriptDelimiter"], request["quoteDialogue"], request.get("subtitleIncludeEmoji", False), job_id)
        else:
            count = writer(staging, base, project, lines, formats, request["scriptDelimiter"], request["quoteDialogue"], request.get("subtitleIncludeEmoji", False), lambda: deps.export_cancel_requested(job_id))
            failures = []
        if deps.export_cancel_requested(job_id):
            raise deps.GenerationCancelled("エクスポートをキャンセルしました。")
        if count == 0:
            raise RuntimeError("生成できた成果物がありません。")
        if layout == "split":
            os.replace(staging, final_path)
            saved_at = final_path
        else:
            commit_joined(staging, destination)
            staging.rmdir()
            saved_at = destination
        return str(saved_at), count, failures
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


deps.register(__name__, [
    "build_export_lines", "clean_export_text", "csv_field", "export_bundle", "line_base_name",
    "joined_timeline", "normalized_file_key", "safe_file_component", "script_text", "srt_text", "truncate_file_name",
    "export_wav_duration", "subtitle_export_text", "validate_split_names",
])
