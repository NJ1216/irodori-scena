export const voiceDesignAges = ["小学校低学年", "小学校高学年", "中学生", "高校生", "大学生", "20代", "30代", "40代", "50代", "60代", "初老", "長老"] as const;
export const voiceDesignGenders = ["男児", "女児", "男の子", "女の子", "男性", "女性", "中性"] as const;
export const voiceDesignPitches = ["かなり低い", "低い", "やや低い", "やや高い", "高い", "かなり高い"] as const;
export const voiceDesignQualities = [
  { label: "質感", values: ["ハスキー", "かすれた", "艶のある", "透明感のある", "甘い", "乾いた", "ざらついた", "金属的"] },
  { label: "厚み", values: ["太い", "細い", "軽い", "重厚"] },
  { label: "息・響き", values: ["息を多く含む", "息が少ない", "鼻にかかった", "胸に響く", "こもった", "よく通る"] },
] as const;
export const voiceDesignStyles = ["優しい", "穏やか", "快活", "落ち着いた", "淡々とした", "上品", "力強い", "威厳のある", "色気のある", "無邪気", "幼い", "ささやくような", "舌足らず", "歯切れがよい", "冷たい", "気だるい", "感情豊か", "おっとり"] as const;

export type VoiceDesign = {
  age?: string;
  gender?: string;
  pitch?: string;
  qualities: string[];
  style?: string;
  notes: string;
};

export const emptyVoiceDesign = (): VoiceDesign => ({ qualities: [], notes: "" });
const allowed = (value: string | undefined, options: readonly string[]) => (value && options.includes(value) ? value : undefined);
export const normalizeVoiceDesign = (value?: Partial<VoiceDesign> | null): VoiceDesign => ({
  age: allowed(value?.age, voiceDesignAges),
  gender: allowed(value?.gender === "中性的" ? "中性" : value?.gender, voiceDesignGenders),
  pitch: allowed(value?.pitch, voiceDesignPitches),
  qualities: Array.isArray(value?.qualities) ? value.qualities.filter((item) => voiceDesignQualities.some((group) => (group.values as readonly string[]).includes(item))) : [],
  style: allowed(value?.style, voiceDesignStyles),
  notes: typeof value?.notes === "string" ? value.notes : "",
});

const sentence = (value: string) => `${value.replace(/[。\s]+$/u, "")}。`;
export function voiceDesignKeywords(value: VoiceDesign): string {
  return [value.age && `${value.age}の声`, value.gender && `${value.gender}の声`, value.pitch && `${value.pitch}声`, ...value.qualities.map((quality) => `${quality}${quality === "ハスキー" ? "な" : ""}声質`), value.style && `${value.style}話し方`, value.notes.trim()]
    .filter((item): item is string => Boolean(item))
    .map(sentence)
    .join("");
}

export const hasVoiceDesignInput = (value: VoiceDesign) => Boolean(value.age || value.gender || value.pitch || value.qualities.length || value.style || value.notes.trim());
