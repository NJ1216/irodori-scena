import type { LoraInputRow } from "../../types/lora";
export function inputProblems(rows: LoraInputRow[]): string[] {
  if (rows.length < 2) return ["学習する音声と台詞を2組以上追加してください。"];
  return rows.flatMap((row) => {
    const label = row.wavName ?? row.textName ?? row.id;
    if (row.blocked) return [`${label}: 対応が曖昧です。素材名を直して取り込み直すか、この行を除外してください。`];
    if (!row.wavName) return [`${label}: 対応するWAVがありません。取り込み直すか、この行を除外してください。`];
    if (!row.text.trim()) return [`${label}: 本文を入力してください。`];
    if (!row.speakerId.trim()) return [`${label}: 話者IDを入力してください。`];
    return row.issues.filter((issue) => !/text|txt|本文/i.test(issue)).map((issue) => `${label}: ${issue}`);
  });
}
export function parseTrainingSettings(steps: string, rate: string) {
  if (!/^\d+$/.test(steps) || !Number.isSafeInteger(Number(steps)) || Number(steps) < 1 || Number(steps) > 100000) throw new Error("学習ステップは1〜100000の整数で入力してください。");
  if (!/^([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$/.test(rate) || !Number.isFinite(Number(rate)) || Number(rate) < 1e-7 || Number(rate) > 0.01) throw new Error("学習率は0.0000001〜0.01の数値で入力してください。");
  return { maxSteps: Number(steps), learningRate: Number(rate) };
}
export function runningJob(status: string) {
  return ["queued", "preparing", "running", "cancelling"].includes(status);
}

export function parseTrainingLimits(batch: string, seconds: string) {
  if (!/^[1-4]$/.test(batch)) throw new Error("バッチサイズは1〜4の整数で入力してください。");
  if (!seconds.trim()) return { batchSize: Number(batch), maxSeconds: null };
  if (!/^([0-9]+(\.[0-9]*)?|\.[0-9]+)$/.test(seconds) || !Number.isFinite(Number(seconds)) || Number(seconds) < 1 || Number(seconds) > 120) throw new Error("1素材の最大秒数は1〜120で入力してください。");
  return { batchSize: Number(batch), maxSeconds: Number(seconds) };
}
