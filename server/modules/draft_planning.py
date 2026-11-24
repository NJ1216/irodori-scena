from __future__ import annotations
from server.app_deps import (
    math,
    re,
    unicodedata,
    Path,
    Any,
    Callable,
    parse_dialogue_protocol,
)
from server.registry import deps
from server.modules.ollama_context import DraftContextError

def draft_reader_introduction(character: dict[str, Any]) -> str:
    """Build narrative fallback copy without exposing the structured profile layout."""
    details = deps.normalize_character_profile_details(character.get("profileDetails"))
    name = str(character.get("name", "")).strip() or "この人物"
    role = str(details.get("role", "")).strip()
    personality = str(details.get("personality", "")).strip()
    if role and personality:
        opening = f"{name}は、{role}を務める{personality}な人物。"
    elif role:
        opening = f"{name}は、{role}として登場する人物。"
    elif personality:
        opening = f"{name}は、{personality}な人物。"
    else:
        opening = f"{name}は、この台本の登場人物。"
    return opening


def select_draft_optional_context(
    request: deps.DraftRequest,
    characters: list[dict[str, Any]],
    *,
    cast_alias_by_id: dict[str, str],
    debug_response_path: Path | None = None,
    on_call: Callable[[], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    job_id: str | None = None,
) -> dict[str, set[str]]:
    """Let the planner select only theme-relevant optional facts."""
    allowed_cast_ids = {str(character.get("id", "")) for character in characters}
    empty = {cast_id: set() for cast_id in allowed_cast_ids}
    inventory = deps.draft_context_inventory(characters, cast_alias_by_id)
    if not any((item["available_optional_fields"] for item in inventory)):
        return empty
    system = """あなたは脚本用コンテキストの選別係です。テーマと実際の設定値を照合し、本当に関連する任意項目だけ選んでください。
一人称、呼び方、性格、話し方など常に守る人物制約は別途渡されます。趣味・好み・特技・過去などは、作者がテーマで明示した場合、または現在の会話目的・判断・反応へ無理なく影響する場合だけ選びます。
「設定が存在する」「使えそう」「人物らしさを出せる」という理由だけで選ばず、無関係な設定を新しい話題や事件のきっかけにしないでください。何も不要なら空の回答が正常です。"""
    try:
        if on_call:
            on_call()
        result = deps.complete_records(
            request,
            contract=deps.context_selection_contract(
                set(cast_alias_by_id.values()), set(deps.DRAFT_OPTIONAL_PROFILE_FIELDS)
            ),
            system=system,
            user={"theme_or_situation": request.theme, "optional_field_inventory": inventory},
            max_tokens=512,
            temperature=0.1,
            sampling_policy="deterministic",
            debug_response_path=debug_response_path,
            should_cancel=should_cancel,
            job_id=job_id,
        )
        if should_cancel and should_cancel():
            raise deps.GenerationCancelled("台本生成をキャンセルしました。")
    except deps.GenerationCancelled:
        raise
    except Exception:
        return empty
    selected_by_alias: dict[str, set[str]] = {}
    for row in result.records:
        selected_by_alias.setdefault(row["cast"], set()).add(row["field"])
    cast_id_by_alias = {alias: cast_id for cast_id, alias in cast_alias_by_id.items()}
    selected = {cast_id: set() for cast_id in allowed_cast_ids}
    for alias, fields in selected_by_alias.items():
        cast_id = cast_id_by_alias.get(alias)
        if cast_id:
            selected[cast_id].update(fields)
    return selected


def draft_expression_guidance(request: deps.DraftRequest) -> tuple[str, str]:
    cast_settings = getattr(request, "cast_settings", {})
    if cast_settings:
        return (
            f"各発話では participating_casts の preferences.emoji に従う。「許可」のキャストだけ演技上適切な表情絵文字を使い、「禁止」のキャストではemoji_annotationsを出さない。{deps.emoji_annotation_schema()}",
            "各発話では participating_casts の preferences.fillers に従う。「多めに自然に入れる」のキャストだけ、考える間・話題転換・反応にフィラーをやや多めに織り交ぜる。ただし毎文には入れず、他のキャストには必要な箇所だけにする。",
        )
    emoji_schema = deps.emoji_annotation_schema()
    emoji = (
        f"Irodori-TTSの表情絵文字を使う。{emoji_schema}"
        if request.emoji_expressions
        else "表情絵文字は使わず、emoji_annotationsを出さない。"
    )
    filler = (
        "フィラーを普段より多めに使う。「え〜と」「んっと」「あの…」などを考える間や反応に自然に織り交ぜる。ただし毎文には入れない。"
        if request.filler_richness
        else "フィラーは必要な箇所にだけ自然に使い、過剰に繰り返さない。"
    )
    return (emoji, filler)


def draft_text_cast_context(cast_context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text_context: list[dict[str, Any]] = []
    for cast in cast_context:
        copied = dict(cast)
        preferences = cast.get("preferences", {})
        if isinstance(preferences, dict):
            copied["preferences"] = {key: value for key, value in preferences.items() if key != "emoji"}
        text_context.append(copied)
    return text_context


def _draft_plan_texts(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _draft_plan_text(value: Any, fallback: str = "") -> str:
    return str(value).strip() if isinstance(value, str) and value.strip() else fallback


def _normalized_draft_chapter(
    raw_chapter: dict[str, Any], number: int, *, fallback_title: str | None = None,
) -> dict[str, Any] | None:
    title = _draft_plan_text(raw_chapter.get("title"), fallback_title or f"第{number}部")
    objective = _draft_plan_text(raw_chapter.get("objective"))[:220]
    beats = [item[:240] for item in _draft_plan_texts(raw_chapter.get("beats"))[:12]]
    continuity = [item[:180] for item in _draft_plan_texts(raw_chapter.get("continuity_requirements"))[:4]]
    if not objective and (not beats):
        return None
    return {
        "title": title[:60],
        "objective": objective or "この章で会話と出来事を前へ進める。",
        "beats": beats or ["登場人物の反応と具体的なやり取りを描く。"],
        "continuity_requirements": continuity or ["これまでに確立した人物設定と関係性を守る。"],
        "opening_state": _draft_plan_text(raw_chapter.get("opening_state"))[:180],
        "closing_state": _draft_plan_text(raw_chapter.get("closing_state"))[:180],
        "novelty_requirement": _draft_plan_text(raw_chapter.get("novelty_requirement"))[:180],
    }


def complete_draft_plan(
    plan: dict[str, Any], request: deps.DraftRequest, *, chunk_count: int
) -> tuple[dict[str, Any], bool]:
    """Return a usable, exactly-sized chapter plan even when the LLM is loose.

    Local models occasionally omit a chapter, return an outline as a single
    object, or over-split one.  The chapter plan is only scaffolding for the
    actual draft, so failing the entire job here is worse than deterministically
    completing that scaffolding while retaining every useful outline detail.
    """
    raw_chapters = plan.get("chapters") if isinstance(plan, dict) else None
    source_chapters = raw_chapters if isinstance(raw_chapters, list) else []
    normalized: list[dict[str, Any]] = []
    for number, raw_chapter in enumerate(source_chapters, start=1):
        if not isinstance(raw_chapter, dict):
            continue
        chapter = _normalized_draft_chapter(raw_chapter, number)
        if chapter:
            normalized.append(chapter)
    repaired = not isinstance(raw_chapters, list) or len(normalized) != chunk_count
    if len(normalized) > chunk_count:
        buckets: list[list[dict[str, Any]]] = [[] for _ in range(chunk_count)]
        for index, chapter in enumerate(normalized):
            bucket = min(chunk_count - 1, index * chunk_count // len(normalized))
            buckets[bucket].append(chapter)
        normalized = [
            {
                "title": "・".join((chapter["title"] for chapter in bucket)),
                "objective": " ".join((chapter["objective"] for chapter in bucket)),
                "beats": [beat for chapter in bucket for beat in chapter["beats"]],
                "continuity_requirements": [item for chapter in bucket for item in chapter["continuity_requirements"]],
                "opening_state": bucket[0].get("opening_state", ""),
                "closing_state": bucket[-1].get("closing_state", ""),
                "novelty_requirement": "・".join(
                    (chapter.get("novelty_requirement", "") for chapter in bucket if chapter.get("novelty_requirement"))
                ),
            }
            for bucket in buckets
            if bucket
        ]
    while len(normalized) < chunk_count:
        number = len(normalized) + 1
        normalized.append(deps.fallback_draft_chapter(request, number, chunk_count))
    completed = dict(plan) if isinstance(plan, dict) else {}
    completed["title"] = str(completed.get("title", "")).strip() or "生成台本"
    completed["story_bible"] = (str(completed.get("story_bible", "")).strip() or request.theme.strip())[:1600]
    completed["chapters"] = normalized[:chunk_count]
    return (completed, repaired)


def create_draft_plan(
    request: deps.DraftRequest,
    *,
    cast_context: list[dict[str, Any]],
    chunk_count: int,
    core_block_count: int | None = None,
    target_characters: int,
    token_budget: int,
    debug_directory: Path,
    on_call: Callable[[int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    job_id: str | None = None,
    benchmark_seed: int | None = None,
) -> dict[str, Any]:
    theme_sections = deps.draft_theme_sections(request.theme)
    outline_policy = deps.draft_outline_policy(request.target_minutes, request.theme)
    story_chapter_count = int(outline_policy["story_chapters"])
    beats_per_chapter = max(2, math.ceil(deps.required_draft_developments(
        target_characters, deps.safe_draft_chapter_characters(token_budget), story_chapter_count) / story_chapter_count))
    system = """あなたは日本語の音声ドラマ脚本の構成作家です。本文台詞はまだ書きません。これは scena-draft-plan-hierarchical-v2 プロトコルです。
長い台本を複数章に分けても、物語・会話・感情の連続性が破綻しない全体設計を作ってください。各章では初めて起こる出来事・明かす情報・感情や関係の変化を決め、前章の言い換え、同じ反応の反復、結末後の蛇足を避けます。
章は物語上のまとまりです。技術的な生成分割数ではありません。作者の章立ては内容を保持し、必要なら自然に統合・分割できます。各章を、モデルが一度で意味的に完結できる場面へ分け、scenes に各場面の purpose・start・end を必ず与えてください。文字数で一場面を分断せず、能力上限を超える内容は開始状態と終了状態が異なる複数場面として設計します。最終章で結末を完了してください。
構成の時点で実際に話す出来事・具体例・質問と答え・判断を決めてください。「近況を語る」「テーマを深掘りする」「盛り上がる」のような枠だけでは本文の内容が不足します。作者が題材を指定していない箇所は、その舞台で自然な具体的内容を創作して各場面へ一度ずつ配分します。挨拶と締めは短く、本編は別々の新情報を持つ複数場面にします。終了状態は「語り続ける」ではなく、その場面で何が分かった・決まった状態かを書いてください。
作者が物語の終了条件を明示している場合だけ、kind=endingのtextにその条件の原文を一字も変えず引用してください。末尾の一文を自動的に結末と解釈しないでください。演出・文体・話し方の指示は結末ではありません。明示条件がなければendingを返さず、最終場面の終了状態で自然に締めてください。明示された結末は最終場面へ一度だけ組み込み、独立した重複場面を追加しないでください。
participating_casts の一人称・呼び方・関係性・話し方と preferences.priority を守ってください。
二人称代名詞と敬称は別の制約です。参加キャスト間の relations.address があれば最優先し、なければ自然な日本語の呼称を選びます。基本の敬称は人名や明示された呼称へ付けるもので、二人称代名詞へ機械的に連結して「あなたさん」「君さん」のような呼び方を作ってはいけません。
theme_or_situation は作者が指定した最上位の事実制約です。キャストの職業・背景・原作世界観は口調や反応の参考に留め、作者が指定していない事件・組織・生死の危機・舞台へ変更してはいけません。
theme_adaptation の mode と instruction に従い、入力の情報量を指定尺に適合させてください。source_sections は作者入力を失わないための証拠であり、章数の指定ではありません。複数区間を一章へ自然に統合して構いません。expandでは作者入力と矛盾しない具体的な進展を創作し、compressでは重要条件と結末を残して説明や枝葉を統合し、preserveでは情報量を保って構成化します。
選別済みの任意設定も使用必須ではなく、自然な場合だけ短く言及できる参考情報です。テーマと現在の会話目的を最優先し、設定を順番に紹介したり台詞で自己申告させたりしないでください。無関係な趣味・好物・苦手・職業・過去を話題や事件のきっかけにせず、設定を使わなくても人物像と矛盾しなければ正常です。作者がテーマ文で明示した設定は題材として優先してください。
キャスト名は participating_casts の name と完全一致させ、簡体字中国語を混ぜず自然な日本語で書いてください。Unicode絵文字は一切出力しないでください。
台本タイトルに加え、各章にも内容を端的に表す短い固有タイトルを付けてください。全体を貫く事実・目的・結末、各章の目的・開始状態・具体的展開・終了状態・新規性・継続条件を返してください。"""
    system += (
        "\nparticipating_casts全員について短いcast記号ごとに一意に、この台本での日本語の役割と"
        "この台本を読む人のための自然な人物紹介を返してください。"
        "短いcast記号ごとに一意に1行ずつ返してください。人物紹介は一〜二文の叙述にし、"
        "小説・漫画の登場人物紹介のように、この台本での立場、性格、他者との関わりを短くまとめてください。"
        "profile内の項目名を転記した「名前：… 読み：… 年齢：…」のようなプロフィール表・データベース表現は禁止です。"
        "reader_facing_introduction_seedは自然文の参考であり、項目表へ展開してはいけません。"
        "演技指示・命令・制作メモ（「〜口調で話す」「〜と呼ぶ」「〜ように接する」など）は書かないでください。"
    )
    user = {
        "participating_casts": cast_context,
        "theme_or_situation": request.theme,
        "source_sections": theme_sections,
        "suggested_story_chapters": story_chapter_count,
        "minimum_developments_per_chapter": beats_per_chapter,
        "target_minutes": request.target_minutes,
        "total_spoken_character_budget": target_characters,
        "theme_adaptation": outline_policy,
    }
    if on_call:
        on_call(1)
    planning_output_tokens = min(token_budget, max(2048, story_chapter_count * beats_per_chapter * 320))
    try:
        result = deps.complete_records(
            request,
            contract=deps.draft_plan_contract({str(item.get("cast", "")) for item in cast_context}),
            system=system,
            user=user,
            max_tokens=planning_output_tokens,
            temperature=0.55,
            debug_response_path=debug_directory / "plan-attempt-1.txt",
            should_cancel=should_cancel,
            job_id=job_id,
            benchmark_seed=benchmark_seed,
        )
    except deps.GenerationCancelled:
        raise
    except Exception as error:
        if isinstance(error, (deps.TransportFailure, DraftContextError)):
            raise
        ending = deps.draft_author_ending(request.theme, theme_sections)
        return {
            "title": "生成台本", "story_bible": request.theme.strip(),
            "chapters": deps.fallback_story_chapters(
                request, story_chapter_count, minimum_beats=beats_per_chapter,
            ),
            "_planning_fallback_used": True,
            "_planning_fallback_reason": f"planning_error:{type(error).__name__}",
            "_source_sections": theme_sections, "_author_ending": ending,
            "_theme_adaptation": outline_policy,
        }
    if should_cancel and should_cancel():
        raise deps.GenerationCancelled("台本生成をキャンセルしました。")
    plan = deps.plan_from_records(result.records)
    raw_chapters = plan.get("chapters", [])
    chapters = []
    for index, raw in enumerate(raw_chapters if isinstance(raw_chapters, list) else []):
        if not isinstance(raw, dict):
            continue
        fallback_title = deps.fallback_draft_chapter(request, index + 1, story_chapter_count)["title"]
        chapter = _normalized_draft_chapter(raw, index + 1, fallback_title=fallback_title)
        if chapter:
            start = index * len(theme_sections) // max(1, len(raw_chapters))
            end = (index + 1) * len(theme_sections) // max(1, len(raw_chapters))
            assigned = theme_sections[start:max(start + 1, end)]
            chapter["chapter_id"] = f"C{len(chapters) + 1}"
            chapter["source_section_ids"] = [section["id"] for section in assigned]
            chapters.append(chapter)
    if chapters:
        completed, _repaired = complete_draft_plan(
            {**plan, "chapters": chapters}, request, chunk_count=story_chapter_count,
        )
        chapters = completed["chapters"]
    fallback_used = not chapters
    fallback_reason = ""
    if not chapters:
        chapters = deps.fallback_story_chapters(
            request, story_chapter_count, minimum_beats=beats_per_chapter,
        )
        if not result.raw_response.strip():
            fallback_reason = "empty_response"
        elif result.transport.partial:
            fallback_reason = "truncated_response_without_usable_chapter"
        else:
            fallback_reason = "no_usable_chapter"
    ending = deps.draft_author_ending(request.theme, theme_sections, plan.get("ending_quotes"))
    if ending:
        chapters[-1]["author_ending"] = ending
        chapters[-1]["closing_state"] = ending["text"]
    plan["chapters"] = chapters
    plan["title"] = str(plan.get("title", "")).strip() or "生成台本"
    plan["story_bible"] = str(plan.get("story_bible", "")).strip() or request.theme.strip()
    plan["_planning_fallback_used"] = fallback_used
    plan["_planning_fallback_reason"] = fallback_reason
    plan["_source_sections"] = theme_sections
    plan["_author_ending"] = ending
    plan["_theme_adaptation"] = outline_policy
    return plan


def detail_draft_chapter(
    request: deps.DraftRequest, *, chapter: dict[str, Any], required: int,
    cast_context: list[dict[str, Any]], token_budget: int, debug_response_path: Path,
    should_cancel: Callable[[], bool] | None = None, job_id: str | None = None,
    benchmark_seed: int | None = None,
) -> list[str]:
    """Ask once for only one deficient story chapter; partial rows remain usable."""
    system = """日本語音声ドラマの一章を詳細化します。本文台詞は書きません。
章の目的、開始・終了状態、作者入力を保持し、既存展開の言い換えではない具体的な章内展開を返してください。
具体的な出来事・判断・会話の進展を一件ずつ返してください。"""
    result = deps.complete_records(
        request, contract=deps.chapter_detail_contract(), system=system,
        user={"chapter": chapter, "participating_casts": cast_context, "required_developments": required},
        max_tokens=min(token_budget, max(512, required * 160)),
        temperature=0.55, debug_response_path=debug_response_path,
        should_cancel=should_cancel, job_id=job_id,
        benchmark_seed=benchmark_seed,
    )
    if should_cancel and should_cancel():
        raise deps.GenerationCancelled("台本生成をキャンセルしました。")
    return [str(row["text"]).strip()[:240] for row in result.records if str(row.get("text", "")).strip()]


def compact_draft_chapter_outline(chapters: list[dict[str, Any]]) -> list[dict[str, str | int]]:
    """The global map is for orientation; only the current chapter needs beats."""
    return [
        {
            "chapter": index + 1,
            "title": str(chapter.get("title", ""))[:60],
            "objective": str(chapter.get("objective", ""))[:160],
            "closing_state": str(chapter.get("closing_state", ""))[:120],
            "novelty_requirement": str(chapter.get("novelty_requirement", ""))[:120],
        }
        for index, chapter in enumerate(chapters)
    ]


def fixed_dialogue_block_characters(
    chapter_target: int, token_budget: int, max_chunk_characters: int | None = None
) -> int:
    """Choose one stable semantic block; observed yield never shrinks it."""
    hardware_safe = max_chunk_characters or deps.safe_draft_chapter_characters(token_budget)
    return min(deps.DRAFT_DIALOGUE_REQUEST_CEILING, hardware_safe, max(deps.MIN_DRAFT_CHUNK_CHARACTERS, chapter_target))


def dialogue_output_token_budget(
    requested_characters: int, provider_budget: int, *, dynamic_output: bool = False,
) -> int:
    """Cap output by requested Japanese dialogue length, not available context."""
    estimated_lines = max(1, math.ceil(requested_characters / 80))
    estimated = math.ceil(requested_characters * 1.5) + (96 * estimated_lines) + 256
    ceiling = provider_budget if dynamic_output else min(provider_budget, deps.DRAFT_DIALOGUE_TOKEN_CEILING)
    return min(ceiling, max(deps.DRAFT_DIALOGUE_TOKEN_FLOOR, estimated))


def planning_output_token_budget(block_count: int, provider_budget: int) -> int:
    """Leave generous completion headroom so a valid late block is not truncated."""
    return min(provider_budget, 16_384, max(8_192, block_count * 1_200))


def draft_dialogue_overall_progress(generated_characters: int, target_characters: int) -> float:
    """Map received spoken text onto the dialogue portion of whole-job progress."""
    fraction = min(1.0, max(0, generated_characters) / max(1, target_characters))
    return round(
        deps.DRAFT_PROGRESS_DIALOGUE_START
        + fraction * (deps.DRAFT_PROGRESS_DIALOGUE_END - deps.DRAFT_PROGRESS_DIALOGUE_START),
        1,
    )


def draft_performance_overall_progress(completed_lines: int, total_lines: int) -> float:
    fraction = min(1.0, max(0, completed_lines) / max(1, total_lines))
    return round(deps.DRAFT_PROGRESS_NOTATION_END + fraction * (99.0 - deps.DRAFT_PROGRESS_NOTATION_END), 1)


def first_dialogue_shot_compatibility_message(chapter_index: int, attempt: int, loop_reason: str | None) -> str | None:
    if chapter_index != 0 or attempt != 1 or (not loop_reason):
        return None
    return "最初の台詞生成で同じ文字列が大量に連続したため中断しました。選択したモデルは、この台本条件では性能または相性が不足している可能性があります。より大きいモデルか別のモデルで再試行してください。"


def draft_dialogue_loop_reason(content: str) -> str | None:
    """Detect a model loop without treating isolated dramatic silence as invalid."""
    texts = [
        unicodedata.normalize("NFKC", str(line.get("text", "")))
        for line in parse_dialogue_protocol(content).get("lines", [])
        if str(line.get("text", "")).strip()
    ]
    if len(texts) >= 12 and len(set(texts[-12:])) == 1:
        return f"同じ台詞「{texts[-1][:40]}」が12回連続しました。"
    if len(texts) >= 20:
        tail = texts[-20:]
        most_common = max((tail.count(value) for value in set(tail)))
        if most_common >= 16:
            return "直近20発話のうち16発話以上が同一内容になりました。"
    normalized_tail = deps.draft_dialogue_signature(str(content)[-8000:])
    if len(normalized_tail) >= 600:
        for unit_length in range(4, 41):
            repeated = re.search(f"(.{{{unit_length}}})\\1{{11,}}", normalized_tail)
            if repeated:
                return "同じ短いパターンが長時間反復されました。"
    return None


def draft_performance_loop_reason(content: str) -> str | None:
    records = re.findall("(?m)^(L\\d+)\\s*\\|", str(content))
    if not records:
        records = re.findall("(?m)^::(?:PERFORMANCE|TRANSITION)\\s+(.+?)\\s*$", str(content))
    if len(records) >= 10 and len(set(records[-10:])) == 1:
        return f"同じ演技レコード「{records[-1][:60]}」が10回連続しました。"
    return None


def draft_dialogue_prompt_records(lines: list[dict[str, Any]], cast_alias_by_id: dict[str, str]) -> str:
    """Represent immutable dialogue without exposing application IDs."""
    return "\n".join(
        (f"{cast_alias_by_id.get(str(line.get('character_id', '')), '?')}|{line.get('text', '')}" for line in lines)
    )


deps.register(
    __name__,
    [
        "_draft_plan_text",
        "_draft_plan_texts",
        "_normalized_draft_chapter",
        "compact_draft_chapter_outline",
        "complete_draft_plan",
        "create_draft_plan",
        "detail_draft_chapter",
        "dialogue_output_token_budget",
        "planning_output_token_budget",
        "draft_dialogue_loop_reason",
        "draft_dialogue_overall_progress",
        "draft_dialogue_prompt_records",
        "draft_reader_introduction",
        "draft_expression_guidance",
        "draft_text_cast_context",
        "draft_performance_loop_reason",
        "draft_performance_overall_progress",
        "first_dialogue_shot_compatibility_message",
        "fixed_dialogue_block_characters",
        "select_draft_optional_context",
    ],
)
