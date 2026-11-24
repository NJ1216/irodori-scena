import { MAX_REFERENCE_SECONDS, referenceOverflowSeconds } from "./voiceDesignReferenceLength";

type Props = {
  candidates: Array<{ id: string; durationSeconds?: number }>;
  baselineCandidateId: string | null;
  emotionCandidateIds: Partial<Record<string, string>>;
};

export function ReferenceLengthNotice({ candidates, baselineCandidateId, emotionCandidateIds }: Props) {
  const overflow = referenceOverflowSeconds(candidates, baselineCandidateId, emotionCandidateIds);
  if (overflow <= 0) return null;
  return (
    <p className="warning-text" role="status">
      選んだクリップの合計が参照ボイスの上限（{MAX_REFERENCE_SECONDS}秒）を超えています。保存すると末尾の{overflow.toFixed(1)}秒（最後の感情クリップ）は使われません。すべて使うには、短い台詞の候補を選んでください。
    </p>
  );
}
