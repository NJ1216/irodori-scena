export type AppearancePriority = "female" | "male" | "common";

const ANIME_HAIRSTYLES = [
  "アシンメトリー",
  "姫カット",
  "サイドカット",
  "ピクシーカット",
  "スパイクヘア",
  "モヒカン",
  "ローポニーテール",
  "ハイポニーテール",
  "サイドポニーテール",
  "ショートポニーテール",
  "低いツインテール",
  "ハーフアップツインテール",
  "片側三つ編み",
  "ツインブレイド",
  "ドリルヘア",
  "縦ロール",
  "髪を下ろす",
];
const FEMALE_HAIRSTYLES = ["ストレート", "ウェーブ", "カールヘア", "ヘアフラップ", "ボブ", "ポニーテール", "ツインテール", "ハーフアップ", "編み込み", "お団子", "三つ編み", "ウルフカット", ...ANIME_HAIRSTYLES];
const MALE_HAIRSTYLES = ["マッシュ", "センターパート", "ツーブロック", "七三分け", "オールバック", "パーマ", "ウルフカット", "コーンロウ", "ドレッド", "アフロ", ...ANIME_HAIRSTYLES];
const FEMALE_OUTFITS = ["カジュアル", "ワンピース", "スカート", "パンツスタイル", "ブレザー制服", "セーラー服", "ドレス", "和服", "浴衣", "パーカー", "ジャージ", "スポーツウェア", "白衣", "アイドル衣装", "ファンタジー衣装", "作業着", "スーツ", "メイド服"];
const MALE_OUTFITS = ["カジュアル", "スーツ", "パンツスタイル", "詰襟制服", "ブレザー制服", "パーカー", "ジャージ", "スポーツウェア", "和服", "浴衣", "白衣", "作業着", "アイドル衣装", "ファンタジー衣装", "タキシード", "ドレス", "セーラー服", "ワンピース"];

export const ACCESSORY_GROUPS = [
  { label: "頭・髪", options: ["ティアラ", "王冠", "小さな王冠", "花冠", "帽子", "キャップ", "ベレー帽", "シルクハット", "麦わら帽子", "ニット帽", "フード", "ヘアピン", "リボン", "カチューシャ", "バレッタ", "かんざし", "髪飾り", "花の髪飾り", "ヘッドドレス", "ベール", "猫耳", "うさ耳", "角"] },
  { label: "顔・目", options: ["眼鏡", "サングラス", "モノクル", "眼帯", "仮面", "マスク", "ゴーグル"] },
  { label: "耳・首", options: ["ピアス", "イヤリング", "イヤーカフ", "ネックレス", "ペンダント", "チョーカー", "首輪", "スカーフ", "マフラー", "ネクタイ", "蝶ネクタイ"] },
  { label: "手・腕", options: ["指輪", "ブレスレット", "腕時計", "手袋", "長手袋", "リストバンド", "アームレット", "付け爪"] },
  { label: "衣装・装飾", options: ["ブローチ", "コサージュ", "勲章", "肩章", "ベルト", "サスペンダー", "エプロン", "マント", "ケープ", "羽衣", "翼", "尻尾"] },
  { label: "持ち物・機器", options: ["バッグ", "ハンドバッグ", "ショルダーバッグ", "リュック", "ポーチ", "傘", "杖", "ステッキ", "扇子", "本", "スマートフォン", "カメラ", "ヘッドホン", "イヤホン", "マイク"] },
] as const;

export const ACCESSORY_OPTIONS = ACCESSORY_GROUPS.flatMap((group) => group.options);

const commonFirst = <T>(first: T[], second: T[]) => [...first, ...second.filter((value) => !first.includes(value))];

export function appearancePriority(gender: string | undefined): AppearancePriority {
  const value = (gender ?? "").trim().normalize("NFKC").toLowerCase();
  if (["女性", "女", "female"].includes(value)) return "female";
  if (["男性", "男", "male"].includes(value)) return "male";
  return "common";
}

export function prioritizedAppearanceOptions(gender: string | undefined) {
  const priority = appearancePriority(gender);
  if (priority === "female")
    return {
      hairstyles: commonFirst(FEMALE_HAIRSTYLES, MALE_HAIRSTYLES),
      outfits: commonFirst(FEMALE_OUTFITS, MALE_OUTFITS),
    };
  if (priority === "male")
    return {
      hairstyles: commonFirst(MALE_HAIRSTYLES, FEMALE_HAIRSTYLES),
      outfits: commonFirst(MALE_OUTFITS, FEMALE_OUTFITS),
    };
  return {
    hairstyles: commonFirst(FEMALE_HAIRSTYLES, MALE_HAIRSTYLES),
    outfits: commonFirst(FEMALE_OUTFITS, MALE_OUTFITS),
  };
}
