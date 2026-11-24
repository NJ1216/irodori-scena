from __future__ import annotations

from server.app_deps import Any, json, re
from server.registry import deps

SUBJECT_TAGS = {"女性キャラクター": "1girl", "男性キャラクター": "1boy", "中性的・その他": "1other", "限定しない": "1person", "": "1person"}
TAG_VALUES: dict[str, dict[str, str]] = {
    "style": dict(zip(["写真風", "アニメ調", "油絵風", "近未来風", "水彩画風"], ["photorealistic", "anime style", "oil painting", "cyberpunk", "watercolor"])),
    "composition": dict(zip(
        ["顔を大きく写す", "顔と胸元を中心に写す", "上半身を写す", "下半身を写す", "膝上まで写す", "全身を写す", "足を画面外にする", "横顔を写す", "広い範囲を写す", "遠近感を強調する", "遠景を霞ませる", "魚眼レンズで写す", "横長のパノラマにする", "消失点を強調する", "余白を活かす", "一部を水中に入れる", "アイソメトリックで描く", "立ち絵として描く", "背景に拡大像を重ねる", "背景に人物像を投影する"],
        ["close-up", "portrait", "upper body", "lower body", "cowboy shot", "full body", "feet out of frame", "profile", "wide shot", "perspective", "atmospheric perspective", "fisheye", "panorama", "vanishing point", "negative space", "partially underwater shot", "isometric", "tachi-e", "zoom layer", "projected inset"],
    )),
    "camera_angle": dict(zip(
        ["正面から撮る", "真横から撮る", "後ろから撮る", "斜めに傾けて撮る", "ドラマチックな斜め構図", "真上から見下ろす", "空中から広く見下ろす", "鳥の目線から見下ろす", "上から見下ろす", "目線の高さから撮る", "下から見上げる", "一人称視点で撮る"],
        ["front view", "from side", "from behind", "dutch angle shot", "dramatic angle", "top-down view", "aerial shot", "birds-eye-view shot", "from above", "eye-level shot", "from below", "pov"],
    )),
    "screen_effect": dict(zip(
        ["光をにじませる", "背景の光を丸くぼかす", "明暗差を強くする", "被写界深度をつける", "光を星形に伸ばす", "影を落とす", "強いレンズフレアを入れる", "レンズフレアを入れる", "周辺を暗くする", "集中線を入れる", "動きをぼかす", "動線を入れる", "スピード線を入れる", "画像を歪ませる", "多重露光で重ねる", "グリッチノイズを入れる", "錯視表現にする", "走査線を入れる", "立体視パターンにする"],
        ["bloom", "bokeh", "chiaroscuro", "depth of field", "diffraction spikes", "drop shadow", "heavy lens flare", "lens flare", "vignetting", "emphasis lines", "motion blur", "motion lines", "speed lines", "distortion", "double exposure", "glitch", "optical illusion", "scanlines", "stereogram"],
    )),
    "pose": dict(zip(["キメポーズ", "立つ", "座る", "ひざまずく", "しゃがむ", "寝そべる", "歩く", "走る", "ジャンプ", "踊る"], ["dynamic pose", "standing", "sitting", "kneeling", "squatting", "lying", "walking", "running", "jumping", "dancing"])),
    "age_impression": dict(zip(["0才", "1~2才", "3~5才", "6~8才", "9~11才", "12~14才", "15~17才", "18~22才", "23~29才", "30~39才", "40~49才", "50~59才", "60~69才", "70~79才", "80才以上"], ["0 years old", "1-2 years old", "3-5 years old", "6-8 years old", "9-11 years old", "12-14 years old", "15-17 years old", "18-22 years old", "23-29 years old", "30-39 years old", "40-49 years old", "50-59 years old", "60-69 years old", "70-79 years old", "80 years old or older"])),
    "body_build": dict(zip(["細身", "標準", "華奢", "筋肉質", "がっしり", "ふくよか"], ["slender", "average build", "petite", "muscular", "stocky", "plump"])),
    "skin_tone": dict(zip(["色白", "明るめ", "標準", "健康的", "褐色", "濃いめ"], ["pale skin", "fair skin", "medium skin", "tan skin", "brown skin", "dark skin"])),
    "face_contour": dict(zip(["丸顔", "卵型", "面長", "逆三角形", "ベース型"], ["round face", "oval face", "long face", "heart-shaped face", "square face"])),
    "eyebrow_shape": dict(zip(["平行眉", "アーチ眉", "上がり眉", "下がり眉", "太眉", "細眉"], ["straight eyebrows", "arched eyebrows", "raised eyebrows", "drooping eyebrows", "thick eyebrows", "thin eyebrows"])),
    "makeup": dict(zip(["ナチュラル", "薄め", "濃いめ", "華やか", "なし"], ["natural makeup", "light makeup", "heavy makeup", "glamorous makeup", "no makeup"])),
    "bust_size": dict(zip(["小さめ", "標準", "大きめ", "とても大きめ"], ["small breasts", "medium breasts", "large breasts", "huge breasts"])),
    "freckles_moles": dict(zip(["なし", "薄いそばかす", "濃いそばかす", "鼻周りのそばかす", "頬のそばかす", "全身のそばかす", "左目の下のほくろ", "右目の下のほくろ", "口元のほくろ", "頬のほくろ", "唇のほくろ", "首のほくろ", "泣きぼくろ", "複数のほくろ", "そばかすとほくろ"], ["", "light freckles", "heavy freckles", "freckles across nose", "freckles on cheeks", "body freckles", "mole under left eye", "mole under right eye", "mole near mouth", "mole on cheek", "mole on lip", "mole on neck", "beauty mark under eye", "multiple moles", "freckles, mole"])),
    "scars": dict(zip(["なし", "額の傷", "眉の傷", "左目の傷", "右目の傷", "鼻の傷", "頬の傷", "口元の傷", "顔を横切る傷", "首の傷", "胸の傷", "背中の傷", "腕の傷", "脚の傷", "全身の傷"], ["", "forehead scar", "eyebrow scar", "scar over left eye", "scar over right eye", "nose scar", "cheek scar", "scar near mouth", "scar across face", "neck scar", "chest scar", "back scar", "arm scar", "leg scar", "multiple scars"])),
    "tattoos": dict(zip(["なし", "顔のタトゥー", "首のタトゥー", "胸のタトゥー", "背中のタトゥー", "肩のタトゥー", "上腕のタトゥー", "前腕のタトゥー", "手のタトゥー", "腰のタトゥー", "太もものタトゥー", "脚のタトゥー", "足首のタトゥー", "ワンポイントタトゥー", "全身のタトゥー"], ["", "face tattoo", "neck tattoo", "chest tattoo", "back tattoo", "shoulder tattoo", "upper arm tattoo", "forearm tattoo", "hand tattoo", "lower back tattoo", "thigh tattoo", "leg tattoo", "ankle tattoo", "small tattoo", "full body tattoo"])),
    "hair_length": dict(zip(["スキンヘッド", "ベリーショート", "ショート", "ミディアム", "ショルダーレングス", "ミッドバックレングス", "ヒップレングス", "フロアレングス"], ["bald", "very short hair", "short hair", "medium hair", "shoulder-length hair", "mid-back hair", "hip-length hair", "floor-length hair"])),
    "hairstyle": dict(zip(
        ["ストレート", "ウェーブ", "カールヘア", "ヘアフラップ", "ボブ", "ポニーテール", "ツインテール", "ハーフアップ", "編み込み", "お団子", "三つ編み", "ウルフカット", "マッシュ", "センターパート", "ツーブロック", "七三分け", "オールバック", "パーマ", "コーンロウ", "ドレッド", "アフロ", "アシンメトリー", "姫カット", "サイドカット", "ピクシーカット", "スパイクヘア", "モヒカン", "ローポニーテール", "ハイポニーテール", "サイドポニーテール", "ショートポニーテール", "低いツインテール", "ハーフアップツインテール", "片側三つ編み", "ツインブレイド", "ドリルヘア", "縦ロール", "髪を下ろす"],
        ["straight hair", "wavy hair", "curly hair", "hair flaps", "bob cut", "ponytail", "twintails", "half updo", "braided hair", "hair bun", "braid", "wolf cut", "mushroom cut", "center-parted hair", "undercut", "side-parted hair", "slicked-back hair", "permed hair", "cornrows", "dreadlocks", "afro", "asymmetrical hair", "hime cut", "sidecut", "pixie cut", "spiked hair", "mohawk", "low ponytail", "high ponytail", "side ponytail", "short ponytail", "low twintails", "half up twintails", "side braid", "twin braids", "drill hair", "ringlets", "hair down"],
    )),
    "hair_texture": dict(zip(["ストレート", "ゆるいウェーブ", "くせ毛", "強いカール", "さらさら", "ふんわり"], ["straight hair", "slightly wavy hair", "messy hair", "tightly curled hair", "silky hair", "fluffy hair"])),
    "bangs": dict(zip(["前髪なし", "ぱっつん", "流し前髪", "センター分け", "斜め前髪", "シースルーバング"], ["no bangs", "blunt bangs", "swept bangs", "parted bangs", "side bangs", "see-through bangs"])),
    "facial_hair": dict(zip(["なし", "無精ひげ", "口ひげ", "あごひげ", "フルビアード"], ["", "stubble", "mustache", "goatee", "full beard"])),
    "eye_style": dict(zip(["たれ目", "切れ長", "つり目", "丸い目", "ぱっちりした目", "細目", "眠たげな目", "ジト目", "三白眼", "猫目"], ["tareme", "narrow eyes", "tsurime", "round eyes", "wide eyes", "slit eyes", "sleepy eyes", "jitome", "sanpaku", "cat eyes"])),
    "outfit_impression": dict(zip(["可愛い系", "甘々系", "ガーリー系", "フェミニン系", "クール系", "きれいめ系", "上品系", "カジュアル系", "ストリート系", "スポーティ系", "モード系", "ボーイッシュ系", "華やか系", "フォーマル系", "レトロ系"], ["cute outfit", "sweet outfit", "girly outfit", "feminine outfit", "cool outfit", "smart casual", "elegant outfit", "casual outfit", "streetwear", "sportswear", "high fashion", "boyish outfit", "glamorous outfit", "formal wear", "retro outfit"])),
    "outfit": dict(zip(["カジュアル", "ワンピース", "スカート", "パンツスタイル", "ブレザー制服", "セーラー服", "ドレス", "和服", "浴衣", "パーカー", "ジャージ", "スポーツウェア", "白衣", "アイドル衣装", "ファンタジー衣装", "作業着", "スーツ", "メイド服", "詰襟制服", "タキシード"], ["casual clothes", "one-piece dress", "skirt", "pants", "school blazer", "sailor uniform", "dress", "traditional Japanese clothes", "yukata", "hoodie", "tracksuit", "sportswear", "lab coat", "idol costume", "fantasy clothes", "work clothes", "suit", "maid", "gakuran", "tuxedo"])),
    "accessory": dict(zip(
        ["ティアラ", "王冠", "小さな王冠", "花冠", "帽子", "キャップ", "ベレー帽", "シルクハット", "麦わら帽子", "ニット帽", "フード", "ヘアピン", "リボン", "カチューシャ", "バレッタ", "かんざし", "髪飾り", "花の髪飾り", "ヘッドドレス", "ベール", "猫耳", "うさ耳", "角", "眼鏡", "サングラス", "モノクル", "眼帯", "仮面", "マスク", "ゴーグル", "ピアス", "イヤリング", "イヤーカフ", "ネックレス", "ペンダント", "チョーカー", "首輪", "スカーフ", "マフラー", "ネクタイ", "蝶ネクタイ", "指輪", "ブレスレット", "腕時計", "手袋", "長手袋", "リストバンド", "アームレット", "付け爪", "ブローチ", "コサージュ", "勲章", "肩章", "ベルト", "サスペンダー", "エプロン", "マント", "ケープ", "羽衣", "翼", "尻尾", "バッグ", "ハンドバッグ", "ショルダーバッグ", "リュック", "ポーチ", "傘", "杖", "ステッキ", "扇子", "本", "スマートフォン", "カメラ", "ヘッドホン", "イヤホン", "マイク"],
        ["tiara", "crown", "mini crown", "flower crown", "hat", "cap", "beret", "top hat", "straw hat", "beanie", "hood", "hairpin", "hair ribbon", "headband", "hairclip", "kanzashi", "hair ornament", "hair flower", "headdress", "veil", "cat ears", "rabbit ears", "horns", "glasses", "sunglasses", "monocle", "eyepatch", "mask", "surgical mask", "goggles", "piercing", "earrings", "ear cuff", "necklace", "pendant", "choker", "collar", "scarf", "muffler", "necktie", "bowtie", "ring", "bracelet", "wristwatch", "gloves", "elbow gloves", "wristband", "armlet", "fake nails", "brooch", "corsage", "medal", "epaulettes", "belt", "suspenders", "apron", "cloak", "cape", "hagoromo", "wings", "tail", "bag", "handbag", "shoulder bag", "backpack", "pouch", "umbrella", "staff", "cane", "folding fan", "book", "smartphone", "camera", "headphones", "earphones", "microphone"],
    )),
    "background": {"あり": "background", "なし": "simple background, white background", "白背景（背景なし）": "simple background, white background", "単色": "simple background", "グラデーション": "gradient background", "室内": "indoors", "教室": "classroom", "カフェ": "cafe", "オフィス": "office", "自宅の部屋": "bedroom", "街中": "city", "住宅街": "residential street", "公園": "park", "森": "forest", "海辺": "beach", "花畑": "flower field", "空": "sky", "夕焼け": "sunset", "夜景": "night cityscape", "ステージ": "stage"},
    "background_gradient_direction": dict(zip(["上から下", "下から上", "左から右", "右から左", "左上から右下", "右上から左下", "放射状"], ["top-to-bottom gradient", "bottom-to-top gradient", "left-to-right gradient", "right-to-left gradient", "diagonal gradient", "reverse diagonal gradient", "radial gradient"])),
}
GESTURE_TAGS = dict(zip(["ピース", "両手でピース", "手を振る", "敬礼", "指差す", "サムズアップ", "指ハート", "ガッツポーズ", "腕を組む", "腰に手", "両手を腰", "手を後ろ"], ["peace sign", "double peace", "waving", "salute", "pointing", "thumbs up", "finger heart", "fist pump", "crossed arms", "hand on hip", "hands on hips", "hands behind back"]))
TAG_VALUES["age_impression"].update({"赤ちゃん": "0 years old", "幼児": "1-2 years old", "幼稚園児": "3-5 years old", "小学校低学年": "6-8 years old", "小学校高学年": "9-11 years old", "中学生": "12-14 years old", "高校生": "15-17 years old", "大学生": "18-22 years old", "青年": "23-29 years old", "成人": "adult", "中年": "middle-aged", "壮年": "mature adult", "初老": "60s", "年配": "70s", "老人": "80 years old or older", "子ども": "child", "十代": "teenager", "若い成人": "young adult"})
TAG_VALUES["accessory"]["なし"] = ""
TAG_VALUES["composition"].update({
    "バストアップ": "upper body", "クローズアップ": "close-up", "ポートレート": "portrait",
    "上半身": "upper body", "カウボーイショット": "cowboy shot", "全身": "full body", "ワイドショット": "wide shot",
})
TAG_VALUES["camera_angle"].update(dict(zip(
    ["正面", "俯瞰", "あおり", "背面", "横から", "横顔", "ダッチアングル", "POV"],
    ["front view", "from above", "from below", "from behind", "from side", "profile", "dutch angle", "pov"],
)))
TAG_VALUES["freckles_moles"].update({"そばかす": "freckles", "ほくろ": "mole"})
TAG_VALUES["scars"].update({"顔の傷": "facial scar", "身体の傷": "body scar"})
TAG_VALUES["tattoos"].update({"ワンポイント": "small tattoo", "腕": "arm tattoo", "背中": "back tattoo"})
TAG_VALUES["occupation"] = dict(zip(
    ["赤ちゃん", "幼稚園児", "小学生", "中学生", "高校生", "大学生", "大学院生", "警察官", "刑事", "消防士", "救急救命士", "自衛官", "警備員", "裁判官", "弁護士", "政治家", "外交官", "医師", "外科医", "歯科医", "看護師", "薬剤師", "獣医師", "介護士", "理学療法士", "研究医", "保育士", "教師", "大学教授", "研究者", "科学者", "司書", "学芸員", "考古学者", "宇宙飛行士", "会社員", "事務員", "経営者", "秘書", "銀行員", "会計士", "建築家", "エンジニア", "プログラマー", "デザイナー", "店員", "ウェイター", "バーテンダー", "料理人", "パティシエ", "ホテルスタッフ", "美容師", "客室乗務員", "巫女", "メイド", "農家", "漁師", "花屋", "庭師", "大工", "整備士", "電気技師", "鉱山作業員", "写真家", "探検家", "パイロット", "船長", "船員", "鉄道員", "駅員", "運転手", "レーサー", "配達員", "陸上選手", "サッカー選手", "野球選手", "バスケットボール選手", "バレーボール選手", "テニス選手", "水泳選手", "体操選手", "ボクサー", "柔道家", "剣道家", "力士", "チアリーダー", "アイドル", "歌手", "俳優", "声優", "ダンサー", "バレリーナ", "モデル", "ミュージシャン", "画家", "漫画家", "作家", "映画監督", "マジシャン", "サーカス団員", "侍", "忍者", "騎士", "王族", "執事", "僧侶", "神官", "魔法使い", "錬金術師", "冒険者", "狩人", "海賊", "占い師", "勇者"],
    ["baby clothes", "kindergartener", "elementary school student", "middle school student", "high school student", "college student", "graduate student", "police officer", "detective", "firefighter", "paramedic", "military uniform", "security guard", "judge", "lawyer", "politician", "diplomat", "doctor", "surgeon", "dentist", "nurse", "pharmacist", "veterinarian", "caregiver", "physical therapist", "medical researcher", "nursery teacher", "teacher", "professor", "researcher", "scientist", "librarian", "museum curator", "archaeologist", "astronaut", "office worker", "office lady", "business executive", "secretary", "banker", "accountant", "architect", "engineer", "programmer", "designer", "shopkeeper", "waiter", "bartender", "chef", "pastry chef", "hotel staff", "hairdresser", "flight attendant", "miko", "maid", "farmer", "fisherman", "florist", "gardener", "carpenter", "mechanic", "electrician", "miner", "photographer", "explorer", "pilot", "captain", "sailor", "railroad worker", "station staff", "driver", "racing driver", "delivery person", "track and field athlete", "soccer player", "baseball player", "basketball player", "volleyball player", "tennis player", "swimmer", "gymnast", "boxer", "judoka", "kendo practitioner", "sumo wrestler", "cheerleader", "idol", "singer", "actor", "voice actor", "dancer", "ballerina", "fashion model", "musician", "painter", "manga artist", "writer", "film director", "magician", "circus performer", "samurai", "ninja", "knight", "royalty", "butler", "monk", "priest", "mage", "alchemist", "adventurer", "hunter", "pirate", "fortune teller", "hero"],
))
EXPRESSIONS = [
    "無表情", "すました表情", "冷静な表情", "眠たげな表情", "目を閉じた表情", "右目でウインク", "左目でウインク", "横目で見る", "上目遣い", "物思いにふける表情", "厳しい表情", "決意に満ちた表情", "疑わしげな表情", "退屈そうな表情", "無関心な表情",
    "穏やかな微笑み", "優しい笑顔", "爽やかな笑顔", "はにかんだ笑顔", "満面の笑み", "自信に満ちた表情", "得意げな表情", "いたずらっぽい笑み", "安堵した微笑み", "照れ笑い", "苦笑い", "口を閉じた笑顔", "歯を見せた笑顔", "大笑い", "ウインクしながら笑う",
    "寂しげな表情", "不安げな表情", "困惑した表情", "落胆した表情", "涙ぐんだ表情", "泣き顔", "号泣", "恐怖", "苦悶の表情", "すすり泣く表情", "涙をこらえた表情", "後悔した表情", "絶望した表情", "傷ついた表情", "哀願する表情",
    "苛立った表情", "にらみつける", "白目をむいた表情", "恍惚とした表情", "狂気的な笑み", "舌を出した表情", "頬を膨らませた表情", "不機嫌な表情", "軽蔑した表情", "歯を食いしばった表情", "激怒した表情", "嫉妬した表情", "挑発的な表情", "気まずい表情", "うんざりした表情",
    "驚いた表情", "唖然", "目を見開いた表情", "口を開けた驚き", "息をのむ表情", "びっくりした表情", "ぎょっとした表情", "困惑した驚き", "嬉しい驚き", "恐怖に驚く表情", "眉を上げた表情", "二度見する表情", "言葉を失った表情", "衝撃を受けた表情", "信じられない表情",
]
EXPRESSION_TAGS = [
    "expressionless", "composed", "calm", "sleepy", "eyes closed", "winking right eye", "winking left eye", "looking to the side", "looking up", "pensive", "stern", "determined", "suspicious", "bored", "indifferent",
    "gentle smile", "kind smile", "bright smile", "shy smile", "grin", "confident", "smug", "mischievous smile", "relieved smile", "embarrassed smile", "wry smile", "closed-mouth smile", "showing teeth", "open-mouth laugh", "winking and smiling",
    "lonely", "worried", "confused", "disappointed", "teary eyes", "crying", "wailing", "scared", "anguished", "sobbing", "holding back tears", "regretful", "despair", "hurt", "pleading",
    "annoyed", "glaring", "rolling eyes", "ecstatic", "crazy smile", "tongue out", "pout", "displeased", "contemptuous", "clenched teeth", "furious", "jealous", "provocative", "awkward", "exasperated",
    "surprised", "stunned", "wide-eyed", "open mouth", "gasp", "startled", "shocked", "surprised and confused", "pleasantly surprised", "surprised and frightened", "raised eyebrows", "double take", "speechless", "in shock", "disbelief",
]
TAG_VALUES["expression"] = dict(zip(EXPRESSIONS, EXPRESSION_TAGS))
GROUPS = {
    "subject": ("subject",), "style": ("style", "composition", "camera_angle", "screen_effect"),
    "body": ("age_impression", "body_build", "height", "bust_size", "skin_tone", "face_contour", "eyebrow_shape", "freckles_moles", "scars", "tattoos", "facial_hair"),
    "hair": ("hair_length", "hairstyle", "hair_texture", "bangs", "hair_color", "secondary_hair_color", "secondary_hair_color_style"),
    "eyes": ("eye_color", "eye_style", "expression"), "outfit": ("occupation", "outfit", "outfit_impression", "accessory"),
    "pose": ("pose", "gestures"), "background": ("background", "background_color", "background_gradient_color1", "background_gradient_color2", "background_gradient_direction"),
}
FIELD_GROUP = {field: group for group, fields in GROUPS.items() for field in fields}
COLOR_NAMES = {
    "red", "scarlet", "crimson", "rose red", "wine red", "ruby", "vermilion", "carmine", "cardinal", "cherry red", "brick red", "maroon", "burgundy", "mahogany", "rust", "coral red", "coral", "salmon", "light salmon", "tomato", "persimmon", "burnt orange", "orange red", "orange", "dark orange", "tangerine", "apricot", "peach", "light peach", "amber", "gold", "goldenrod", "ochre", "mustard", "yellow", "lemon yellow", "canary yellow", "light yellow", "cream", "ivory", "beige", "khaki", "olive", "olive drab", "chartreuse", "lime", "lime green", "yellow green", "spring green", "pale green", "green", "forest green", "emerald", "jade", "shamrock", "sea green", "mint", "mint green", "aquamarine", "turquoise", "dark turquoise", "teal", "cyan", "aqua", "celadon", "sage green", "sky blue", "light blue", "powder blue", "baby blue", "robin egg blue", "cerulean", "azure", "blue", "royal blue", "cornflower blue", "steel blue", "denim blue", "cobalt blue", "sapphire", "navy blue", "midnight blue", "indigo", "periwinkle", "lavender", "light lavender", "violet", "blue violet", "purple", "dark purple", "amethyst", "plum", "mauve", "orchid", "magenta", "fuchsia", "hot pink", "deep pink", "pink", "light pink", "rose pink", "blush", "dusty rose", "raspberry", "watermelon", "black", "charcoal", "slate gray", "gray", "silver", "white", "snow white", "brown", "chocolate", "sienna", "tan", "camel", "copper", "bronze", "black brown",
}
MULTI_VALUE_FIELDS = {"freckles_moles", "facial_hair", "scars", "tattoos", "accessory"}


def _preset_tag(field: str, value: str, request: deps.ImagePromptSuggestionRequest) -> str | None:
    value = value.strip()
    if field == "subject":
        return f"{SUBJECT_TAGS[value]}, solo" if value in SUBJECT_TAGS else None
    if not value:
        return ""
    if field == "height" and re.fullmatch(r"(?:1\d{2}|200)cm", value):
        return value if int(value[:-2]) % 5 == 0 else None
    if field == "background_color" and request.background != "単色":
        return ""
    if field.startswith("background_gradient_") and request.background != "グラデーション":
        return ""
    if field in {"hair_color", "secondary_hair_color", "eye_color", "background_color", "background_gradient_color1", "background_gradient_color2"}:
        if field.startswith("background_") and value in COLOR_NAMES:
            return f"{value} background" if field == "background_color" else value
        suffix = "eyes" if field == "eye_color" else "hair"
        return f"{value} {suffix}" if value in COLOR_NAMES else None
    if field == "secondary_hair_color_style":
        if not request.secondary_hair_color_enabled:
            return ""
        return dict(zip(["インナーカラー", "毛先カラー", "グラデーション", "左右分け", "メッシュ", "ツートーン"], ["colored inner hair", "colored tips", "gradient hair", "split-color hair", "streaked hair", "two-tone hair"])).get(value)
    if field == "gestures":
        return ", ".join(GESTURE_TAGS[item] for item in request.gestures if item in GESTURE_TAGS)
    if field in MULTI_VALUE_FIELDS:
        values = [item.strip() for item in value.split(",") if item.strip()]
        tags = [TAG_VALUES[field].get(item) for item in values]
        return ", ".join(tag for tag in tags if tag) if all(tag is not None for tag in tags) else None
    return TAG_VALUES.get(field, {}).get(value)


def custom_fields(request: deps.ImagePromptSuggestionRequest) -> dict[str, str]:
    custom: dict[str, str] = {}
    for field in FIELD_GROUP:
        if field.startswith("secondary_") and not request.secondary_hair_color_enabled:
            continue
        if field == "gestures":
            continue
        value = request.subject if field == "subject" else str(getattr(request, field, ""))
        if value.strip() and _preset_tag(field, value, request) is None:
            custom[field] = value.strip()
    if request.request.strip():
        custom["request"] = request.request.strip()
    return custom


def clean_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        value = ", ".join(item for item in value if isinstance(item, str))
    if not isinstance(value, str):
        return []
    value = re.sub(r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}|<[^<>]*>", "", value)
    value = re.sub(r"[^\x20-\x7E]", "", value)
    return [tag.strip(" ._-") for tag in value.split(",") if 1 < len(tag.strip(" ._-")) <= 80 and "|" not in tag]


def _custom_tag_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    records = value.get("records")
    if isinstance(records, list):
        return [record for record in records if isinstance(record, dict)]
    wrapped = value.get("custom_fields")
    if isinstance(wrapped, dict):
        value = wrapped
    return [
        {"field": field, **record}
        for field, record in value.items()
        if isinstance(field, str) and isinstance(record, dict)
    ]


def _complete_json_objects(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    objects = []
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    return objects


def parse_custom_tags(value: str, expected: set[str]) -> dict[str, tuple[str, list[str]]]:
    text = value.replace("\r\n", "\n").strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    text = fence.group(1) if fence else text
    candidates: list[dict[str, Any]] = []
    try:
        parsed = json.loads(text)
        candidates.extend(_custom_tag_records(parsed))
    except (TypeError, ValueError):
        for parsed in _complete_json_objects(text):
            if "field" in parsed:
                candidates.append(parsed)
            else:
                candidates.extend(_custom_tag_records(parsed))
        for match in re.finditer(r'"([^"\\]+)"\s*:\s*(\{[^{}]*\})', text):
            try:
                record = json.loads(match.group(2))
            except ValueError:
                continue
            if isinstance(record, dict):
                candidates.append({"field": match.group(1), **record})
    accepted = {}
    for record in candidates:
        field = record.get("field")
        if not isinstance(field, str) or field not in expected:
            continue
        category = _tag_group(field, record.get("category"))
        tags = clean_tags(record.get("tags"))
        if category and tags:
            accepted[field] = (category, tags)
    return accepted


def _tag_group(field: str, category: Any) -> str | None:
    if field != "request":
        return FIELD_GROUP.get(field)
    return category if isinstance(category, str) and category in GROUPS else None


def deterministic_groups(request: deps.ImagePromptSuggestionRequest) -> dict[str, list[str]]:
    result = {group: [] for group in GROUPS}
    for group, fields in GROUPS.items():
        for field in fields:
            value = request.subject if field == "subject" else str(getattr(request, field, ""))
            tag = _preset_tag(field, value, request)
            if tag:
                result[group].extend(clean_tags(tag))
    return result


def join_groups(groups: dict[str, list[str]]) -> str:
    seen: set[str] = set()
    result = []
    for group in GROUPS:
        for tag in groups[group]:
            if tag.casefold() not in seen:
                seen.add(tag.casefold())
                result.append(tag)
    return ", ".join(result)


def convert_custom_fields(request: deps.ImagePromptSuggestionRequest, custom: dict[str, str]) -> dict[str, tuple[str, list[str]]]:
    system = (
        "画像モデル用の短い英語Danbooruタグへ変換する。入力にない特徴を補わない。"
        "各入力キーを保持し、categoryは subject/style/body/hair/eyes/outfit/pose/background のいずれかにする。"
        "requestだけは内容に応じて分類する。絵文字、注釈、未知キーは禁止。主体タグには人数を含めない。"
        "JSONはrecords配列で返す。各recordはfield, category, tagsを持ち、tagsは文字列または文字列配列にする。"
    )
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "field": {"type": "string", "enum": list(custom)},
        "category": {"type": "string", "enum": list(GROUPS)},
        "tags": {"type": ["string", "array"], "items": {"type": "string"}},
    }, "required": ["field", "category", "tags"]}
    def legacy(content):
        return [{"field": field, "category": category, "tags": tags}
                for field, (category, tags) in parse_custom_tags(content, set(custom)).items()]
    contract = deps.LlmRecordContract(
        "image-prompt", 1, schema, "field", frozenset(custom),
        legacy_suffix="JSON {records:[{field,category,tags}]} を返す。tagsは文字列または文字列配列とする。",
        legacy_parser=legacy,
        record_extractor=lambda content: (legacy(content), not content.rstrip().endswith("}")),
    )
    result = deps.complete_records(
        request, contract=contract, system=system, user={"custom_fields": custom}, max_tokens=900,
        temperature=0.2,
        debug_response_path=deps.draft_debug_directory(f"image-prompt-suggestion-{deps.new_id('request')}") / "attempt-1.txt",
    )
    converted = {}
    for row in result.records:
        field = row.get("field")
        if not isinstance(field, str) or field not in custom:
            continue
        group = _tag_group(field, row.get("category"))
        tags = clean_tags(row.get("tags"))
        if group and tags:
            converted[field] = (group, tags)
    return converted


def build_image_prompt(request: deps.ImagePromptSuggestionRequest, converted: dict[str, tuple[str, list[str]]] | None = None) -> dict[str, Any]:
    custom = custom_fields(request)
    groups = deterministic_groups(request)
    converted = converted or {}
    for field, (group, tags) in converted.items():
        groups[group].extend([f"{tags[0]}, solo"] if field == "subject" else tags)
    ignored = [field for field in custom if field not in converted]
    warnings = [f"自由入力を変換できなかったため無視しました: {', '.join(ignored)}"] if ignored else []
    return {"imagePrompt": join_groups(groups), "usedLlm": bool(custom), "ignoredCustomFields": ignored, "warnings": warnings}


@deps.app.post("/api/characters/image-prompt-suggestion")
def suggest_character_image_prompt(request: deps.ImagePromptSuggestionApiRequest) -> dict[str, Any]:
    request = deps.ImagePromptSuggestionRequest.model_validate(request.model_dump())
    custom = custom_fields(request)
    if not custom:
        return build_image_prompt(request)
    try:
        converted = deps.track_default_llm_usage("画像プロンプト提案", lambda: convert_custom_fields(request, custom))
    except RuntimeError:
        converted = {}
    return build_image_prompt(request, converted)


deps.register(__name__, ["build_image_prompt", "convert_custom_fields", "custom_fields", "parse_custom_tags", "suggest_character_image_prompt"])
