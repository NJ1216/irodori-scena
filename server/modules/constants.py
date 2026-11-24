from __future__ import annotations

import os
import re

from server.app_deps import threading, Path
from server.registry import deps

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# A shipped .app is read-only. Its supervisor points this to Application
# Support; development retains the repository-local scratch area.
DATA_ROOT = Path(os.environ.get("SCENA_DATA_ROOT", PROJECT_ROOT / "scena-data")).expanduser()

LLM_DEBUG_ROOT = DATA_ROOT / "debug" / "llm-drafts"

DEVELOPMENT_MODE_ENABLED = os.environ.get("SCENA_DEV_MODE") == "1"
LLM_DEBUG_ENABLED = DEVELOPMENT_MODE_ENABLED

LLM_YIELD_PROFILES_FILE = DATA_ROOT / "llm-yield-profiles.json"

LOCAL_LLM_ROOT = DATA_ROOT / "local-llm"

APP_STATE_FILE = DATA_ROOT / "app-state.json"

CONNECTION_SETTINGS_FILE = DATA_ROOT / "connection-settings.json"

TTS_ASSETS_ROOT = DATA_ROOT / "tts"
TTS_ENGINES_ROOT = TTS_ASSETS_ROOT / "engines"
TTS_ENVIRONMENTS_ROOT = TTS_ASSETS_ROOT / "environments"
TTS_MODELS_ROOT = TTS_ASSETS_ROOT / "models"
TTS_CODECS_ROOT = TTS_ASSETS_ROOT / "codecs"
TTS_DOWNLOADS_ROOT = TTS_ASSETS_ROOT / "downloads"
TTS_REGISTRY_FILE = TTS_ASSETS_ROOT / "registry.json"

RHUBARB_ROOT = DATA_ROOT / "lipsync" / "rhubarb"
RHUBARB_RUNTIMES_ROOT = RHUBARB_ROOT / "runtimes"
RHUBARB_DOWNLOADS_ROOT = RHUBARB_ROOT / "downloads"
RHUBARB_CACHE_ROOT = RHUBARB_ROOT / "cache"

KEYCHAIN_SERVICE = "com.irodori-scena.llm-api-key"

KEYCHAIN_API_KEY_MARKER = "__irodori_scena_keychain__"

GLOBAL_CHARACTERS_ROOT = DATA_ROOT / "global-characters"

GLOBAL_CHARACTERS_FILE = GLOBAL_CHARACTERS_ROOT / "characters.json"

GLOBAL_MEDIA_ROOT = GLOBAL_CHARACTERS_ROOT / "media"

ACTIVE_PROJECT_ROOT = DATA_ROOT

ACTIVE_PROJECT_PATH: Path | None = None

PROJECT_FILE = ACTIVE_PROJECT_ROOT / "project.json"

MEDIA_ROOT = ACTIVE_PROJECT_ROOT / "media"

PROJECT_ROOT_LOCK = threading.RLock()

ENGINE_DEFAULT = PROJECT_ROOT.parent / "_ExternalRepos" / "Irodori-TTS"

VOICE_SAMPLE_TEXT = "こんにちは。私はあなたの物語に寄り添うために、ここにいます。"

CHECKPOINT = "Aratako/Irodori-TTS-v4.1-Small"

MTP_TARGET_REPO = "mlx-community/gemma-4-31b-it-nvfp4"

MTP_TARGET_REVISION = "a0a935b105621b98907915fa12f05348bb9c3c24"

MAX_DRAFT_CHUNK_CHARACTERS = 5000

MIN_DRAFT_CHUNK_CHARACTERS = 160

DRAFT_CHUNK_TARGET_TOKEN_RATIO = 0.25

DRAFT_MAX_DIALOGUE_CALLS = 2

DRAFT_DIALOGUE_TOKEN_FLOOR = 1024

DRAFT_DIALOGUE_TOKEN_CEILING = 6144

# A dialogue response needs room for the line protocol and ordinary Japanese
# punctuation in addition to the spoken text itself.
DRAFT_DIALOGUE_TOKEN_OVERHEAD = 768
DRAFT_CONTEXT_SAFETY_MARGIN = 1024
DRAFT_PROMPT_TOKEN_ESTIMATE_FLOOR = 1024

DRAFT_PERFORMANCE_TOKEN_CEILING = 8192

DRAFT_DIALOGUE_REQUEST_CEILING = 5000

DRAFT_DEFAULT_YIELD_RATIO = 0.45

DRAFT_MIN_YIELD_RATIO = 0.25

DRAFT_MAX_YIELD_RATIO = 1.00

DRAFT_GENERATION_TARGET_RATIO = 1.10

DRAFT_FIRST_PACKET_HEADROOM = 1.20

# Observed dialogue yield fluctuates between calls even for the same model.
# Keep modest headroom without systematically overproducing dialogue.
DRAFT_FORWARD_REQUEST_HEADROOM = 1.07

DRAFT_CONTINUITY_MAX_CHARS = 900

DRAFT_LOOKAHEAD_LINE_COUNT = 3

DRAFT_PROGRESS_CONTEXT = 10.0

DRAFT_PROGRESS_PLANNING = 20.0

DRAFT_PROGRESS_DIALOGUE_START = 20.0

DRAFT_PROGRESS_DIALOGUE_END = 90.0
DRAFT_PROGRESS_NOTATION_END = 95.0

LINE_SPEECH_RATE_MIN = 0.85

LINE_SPEECH_RATE_MAX = 1.35

LINE_SPEECH_RATE_PREFERRED_MIN = 0.95

LINE_SPEECH_RATE_PREFERRED_MAX = 1.2

DISALLOWED_SIMPLIFIED_CHINESE = frozenset(
    "这么说为个门见听话让过对吗没实问间开关应现样从进远动觉认给带种书车东长难无乐头脸们处变并层压严亲纱还"
)

IRODORI_EMOJI_CATALOG: tuple[tuple[str, str, str], ...] = (
    ("👂", "囁き", "耳元の音"),
    ("😮\u200d💨", "吐息", "溜息、寝息"),
    ("⏸️", "間", "沈黙"),
    ("🤭", "笑い", "くすくす、含み笑い"),
    ("🥵", "喘ぎ", "うめき声、唸り声"),
    ("📢", "エコー", "リバーブ"),
    ("😏", "からかう", "甘えるように"),
    ("🥺", "震え声", "自信なさげに"),
    ("🌬️", "息切れ", "荒い息遣い、呼吸音"),
    ("😮", "息をのむ", "Gasp"),
    ("👅", "舐める音", "咀嚼音、水音"),
    ("💋", "リップノイズ", "Lip smack"),
    ("🫶", "優しく", "Tenderly"),
    ("😭", "泣き声", "嗚咽、悲しみ"),
    ("😱", "悲鳴", "叫び、絶叫"),
    ("😪", "眠そう", "気だるげに"),
    ("😴", "寝言", "いびき"),
    ("⏩", "早口", "一気に、急いで"),
    ("📞", "電話越し", "スピーカー越し"),
    ("🐢", "ゆっくり", "Slowly"),
    ("🥤", "飲み込む", "唾を飲む音"),
    ("🤧", "咳・鼻", "咳き込み、鼻すすり"),
    ("😒", "舌打ち", "Tutting"),
    ("😰", "慌てる", "動揺、緊張、どもり"),
    ("😆", "喜び", "嬉しそうに"),
    ("💥", "勢いよく", "力強い勢い"),
    ("😠", "怒り", "不満げ、拗ねる"),
    ("😲", "驚き", "感嘆"),
    ("🥱", "あくび", "Yawn"),
    ("😖", "苦しげ", "Agonizingly"),
    ("😟", "心配", "不安そうに"),
    ("🫣", "照れ", "恥ずかしそうに"),
    ("🙄", "呆れ", "Exasperatedly"),
    ("😊", "楽しげ", "嬉しそうに"),
    ("😎", "得意げ", "自信ありげに"),
    ("👌", "相槌", "頷く音"),
    ("🙏", "懇願", "お願いするように"),
    ("🥴", "酔う", "Drunkenly"),
    ("🎵", "鼻歌", "Humming"),
    ("🤐", "口を塞ぐ", "Muffled"),
    ("😌", "安堵", "満足げに"),
    ("🤔", "疑問", "Questioning"),
    ("💪", "力強く", "力を込めて"),
    ("👃", "嗅ぐ音", "匂いを嗅ぐ音"),
    ("📖", "朗読", "ナレーション"),
)

IRODORI_EMOJIS = frozenset((item[0] for item in IRODORI_EMOJI_CATALOG))

NEGATIVE_TTS_CAPTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("echo-disabled", re.compile(r"(?:エコー|反響)(?:を)?(?:使わない|かけない|掛けない|させない|させず|なし|不要)")),
    ("reverb-disabled", re.compile(r"(?:リバーブ|残響)(?:を)?(?:使わない|かけない|掛けない|避ける|なし|不要)")),
    ("telephone-effect-disabled", re.compile(r"電話(?:越し|音質|効果)?(?:は|を)?(?:使わない|避ける|なし|不要)")),
)


def prohibited_negative_tts_caption_reason(value: str) -> str | None:
    """Reject explicit effect negation without treating lexical `ない` as negation."""
    compact = re.sub(r"\s+", "", value)
    return next((reason for reason, pattern in NEGATIVE_TTS_CAPTION_PATTERNS if pattern.search(compact)), None)

# Keep every officially supported emoji available for manual editing and parsing,
# while withholding known-unreliable effects from LLM-authored suggestions.
AI_PROPOSABLE_EMOJI_CATALOG = tuple(item for item in IRODORI_EMOJI_CATALOG if item[0] != "🤐")
AI_PROPOSABLE_EMOJIS = frozenset(item[0] for item in AI_PROPOSABLE_EMOJI_CATALOG)

TAIL_EVENT_EMOJIS = frozenset(
    {"😮\u200d💨", "🤭", "🥵", "🌬️", "😮", "👅", "💋", "🫶", "😭", "😱", "😴", "🥤", "🤧", "😒", "🥱", "🎵", "👌", "👃"}
)

EMOJI_PLACEMENTS = frozenset({"line_start", "before_phrase", "line_end"})

EMOJI_MAX_REPEATS_PER_TEXT_EFFECT = 3

EMOJI_PERFORMANCE_RULEBOOK = """【SCENA 表情EMOJI演出ルール】
1. まず意図を「話し方」「非言語音」「音響効果」「間・速度」に分類し、直接対応するEMOJIを選ぶ。話し方: 👂・😏・🥺・🫶・😪・⏩・🐢・😰・😆・💥・😠・😲・😖・😟・🫣・🙄・😊・😎・🙏・🥴・😌・🤔・💪・📖。非言語音: 😮‍💨・🤭・🥵・🌬️・😮・👅・💋・😭・😱・😴・🥤・🤧・😒・🥱・🎵・👌・👃。音響効果: 📢・📞。間: ⏸️。
2. 行全体の基本テンポはrateで決め、局所的なテンポ・感情・声色は効かせたい最短語句の直前のEMOJIで決める。たとえば低いrateでも急がせたい語句の直前に⏩、高いrateでもためらわせたい語句の直前に🐢を置ける。
3. 非言語音はその音を入れたい位置に置き、文末なら発話後に続ける。咳、くしゃみ、舌打ち、あくび、飲み込み、鼻歌、いびき、咀嚼、相槌などは、本文またはト書きにその動作・音の根拠がある場合だけ使う。ただし😮‍💨・🤭・😭は、文脈から自然な吐息・含み笑い・泣き声が明確な場合も使える。
4. 似たEMOJIを混同しない。😮は実際に息をのむ音、😲は驚いた話し方。😪は眠そうな話し方、😴は寝言・いびき。👃は匂いを嗅ぐ音、🤧は咳・鼻すすり・くしゃみ・咳払い。📞は電話・スピーカー越し、📢はエコー・リバーブ。👌は実際の相槌・頷く音であり、文中の間や⏸️の代用にしない。🎵は実際の鼻歌で、楽しげな話し方には😊または😆を使う。🥤は実際に唾を飲み込む音で、飲み物や飲酒場面の記号にしない。
5. 📢は叫び・大声・強調を表すEMOJIではない。エコーまたはリバーブを実際に掛ける特殊演出専用であり、電話越し・反響する場所・内心など、その音響効果に特別な理由がある場合だけに使う。声量を上げたいだけなら😱・💥・😠など適切なEMOJI、rate、ト書きを使い、📢は使わない。
6. 同じ位置のEMOJIは原則1個にする。2個は明確に強調したい箇所だけ、3個は特別に強調したい箇所だけに限る。異種の組み合わせと同種反復は許可するが、機械的に複数化しない。例: 🐢🥺😖は、ゆっくり・自信なさそう・苦しげを特別に同時強調し、🐢🐢🥺は🐢の効果を特別に強める。同種反復で非言語音の長さ・回数・音量が比例して増えるとは仮定しない。4個以上は先頭3個だけを採用する。
7. 複合演技では、語句の直前の表情と文末の非言語音を組み合わせてよい。例: 「😭そんなひどいこと、言わないで…😭」は、前者で「そんなひどいこと」の言い方を悲しませ、後者で発話後の泣き声を狙う。
8. 効果が明確な箇所だけに使い、判断できない場合はEMOJIなしを選ぶ。全行への機械的な付与や、本文・ト書きへの説明文の追加はしない。効果解除用のEMOJIがあるとは仮定せず、局所効果は必要な最短語句にだけ指定する。
9. 発話後の非言語音は音声を延ばす可能性がある。直後の発話間隔を短くする目的で、line_endの非言語音と小さなgapを機械的に併用しない。
10. placementは、行全体の声色にはline_start、特定語句の言い方にはbefore_phrase、発話後の独立した非言語音または発話末尾へ効かせる効果にはline_endを使う。同じ演技意図を複数のplacementへ重複させない。
12. 😒は不満・嫌悪・呆れの感情記号ではなく、実際の舌打ち音専用。使う行はト書きにも「舌打ち」と明記し、実音を入れたい位置だけに置く。
13. 🤐は現行モデルで効果の再現性を確認できるまでAIから提案しない。手動で入力された🤐は削除・置換しない。
14. 🤔・👌・🫶は配置で効果範囲を使い分け、三配置のうち一つだけを選ぶ。line_startは発話冒頭から行全体、before_phraseは対象の一単語・最短語句だけ、line_endは文全体の語尾へ効かせる。🤔はline_startで冒頭に「ん？」と首をかしげるニュアンス、before_phraseで対象語だけを疑問調にして一度途切れるような間、line_endで文全体の語尾を疑問調にする。👌は相槌・頷く音、🫶は優しく寄り添う言い方という本来の用途を保ち、記号の見た目だけで機械的に付けない。"""


def enforce_tutting_intent(text: str, stage_direction: str) -> str:
    """Discard AI-authored tutting annotations without explicit sound intent."""
    return text if "😒" not in text or "舌打ち" in stage_direction else text.replace("😒", "")


def emoji_annotation_schema() -> str:
    emoji_catalog = "、".join(
        (f"{emoji}={label}（{description}）" for emoji, label, description in AI_PROPOSABLE_EMOJI_CATALOG)
    )
    return f"本文とト書きには絵文字を直接書かず、各行のemoji_annotationsへ必要な件数だけ指定する。使える絵文字と用途は次だけ: {emoji_catalog}。annotationはemoji、placement、targetを持つ。placementは、行全体へ効かせるline_start、特定語句の直前へ置くbefore_phrase、発話後の非言語音または発話末尾へ効かせるline_end。before_phraseではtargetに本文中の完全一致の語句を入れる。同じ位置に置くannotationは原則1件、明確な強調で2件、特別な強調で最大3件にする。ト書きに絵文字を入れない。\n{EMOJI_PERFORMANCE_RULEBOOK}"


deps.register(
    __name__,
    [
        "ACTIVE_PROJECT_ROOT",
        "ACTIVE_PROJECT_PATH",
        "AI_PROPOSABLE_EMOJI_CATALOG",
        "AI_PROPOSABLE_EMOJIS",
        "APP_STATE_FILE",
        "prohibited_negative_tts_caption_reason",
        "CHECKPOINT",
        "CONNECTION_SETTINGS_FILE",
        "TTS_ASSETS_ROOT",
        "TTS_ENGINES_ROOT",
        "TTS_ENVIRONMENTS_ROOT",
        "TTS_MODELS_ROOT",
        "TTS_CODECS_ROOT",
        "TTS_DOWNLOADS_ROOT",
        "TTS_REGISTRY_FILE",
        "RHUBARB_ROOT",
        "RHUBARB_RUNTIMES_ROOT",
        "RHUBARB_DOWNLOADS_ROOT",
        "RHUBARB_CACHE_ROOT",
        "DATA_ROOT",
        "DISALLOWED_SIMPLIFIED_CHINESE",
        "DRAFT_CHUNK_TARGET_TOKEN_RATIO",
        "DRAFT_CONTINUITY_MAX_CHARS",
        "DRAFT_CONTEXT_SAFETY_MARGIN",
        "DRAFT_DEFAULT_YIELD_RATIO",
        "DRAFT_FORWARD_REQUEST_HEADROOM",
        "DRAFT_FIRST_PACKET_HEADROOM",
        "DRAFT_GENERATION_TARGET_RATIO",
        "DRAFT_DIALOGUE_REQUEST_CEILING",
        "DRAFT_DIALOGUE_TOKEN_CEILING",
        "DRAFT_DIALOGUE_TOKEN_FLOOR",
        "DRAFT_DIALOGUE_TOKEN_OVERHEAD",
        "DRAFT_LOOKAHEAD_LINE_COUNT",
        "DRAFT_MAX_DIALOGUE_CALLS",
        "DRAFT_MAX_YIELD_RATIO",
        "DRAFT_MIN_YIELD_RATIO",
        "DRAFT_PERFORMANCE_TOKEN_CEILING",
        "DRAFT_PROGRESS_CONTEXT",
        "DRAFT_PROGRESS_DIALOGUE_END",
        "DRAFT_PROGRESS_NOTATION_END",
        "DRAFT_PROGRESS_DIALOGUE_START",
        "DRAFT_PROGRESS_PLANNING",
        "DRAFT_PROMPT_TOKEN_ESTIMATE_FLOOR",
        "EMOJI_MAX_REPEATS_PER_TEXT_EFFECT",
        "enforce_tutting_intent",
        "EMOJI_PERFORMANCE_RULEBOOK",
        "EMOJI_PLACEMENTS",
        "ENGINE_DEFAULT",
        "GLOBAL_CHARACTERS_FILE",
        "GLOBAL_CHARACTERS_ROOT",
        "GLOBAL_MEDIA_ROOT",
        "IRODORI_EMOJIS",
        "IRODORI_EMOJI_CATALOG",
        "KEYCHAIN_API_KEY_MARKER",
        "KEYCHAIN_SERVICE",
        "LINE_SPEECH_RATE_MAX",
        "LINE_SPEECH_RATE_MIN",
        "LINE_SPEECH_RATE_PREFERRED_MAX",
        "LINE_SPEECH_RATE_PREFERRED_MIN",
        "LLM_DEBUG_ROOT",
        "DEVELOPMENT_MODE_ENABLED",
        "LLM_DEBUG_ENABLED",
        "LOCAL_LLM_ROOT",
        "LLM_YIELD_PROFILES_FILE",
        "MAX_DRAFT_CHUNK_CHARACTERS",
        "MEDIA_ROOT",
        "MIN_DRAFT_CHUNK_CHARACTERS",
        "MTP_TARGET_REPO",
        "MTP_TARGET_REVISION",
        "PROJECT_FILE",
        "PROJECT_ROOT",
        "PROJECT_ROOT_LOCK",
        "TAIL_EVENT_EMOJIS",
        "VOICE_SAMPLE_TEXT",
        "emoji_annotation_schema",
    ],
)
