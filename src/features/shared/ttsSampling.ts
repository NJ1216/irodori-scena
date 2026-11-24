import type { Take, TtsProjectSelection } from "../../types";

export const MEANFLOW_MODEL_REPO = "Aratako/Irodori-TTS-v4.1-Small-MF";
export const MEANFLOW_MODEL_REVISION = "ccc78f5d480b6e51b69b2d5042a14c4da04fea6e";

export function isMeanFlowSelection(selection: TtsProjectSelection | null | undefined) {
  return selection?.model?.repo === MEANFLOW_MODEL_REPO && selection.model.revision === MEANFLOW_MODEL_REVISION;
}

export function takeSamplingPresentation(take: Take) {
  if (take.ttsConfiguration?.modelRevision === MEANFLOW_MODEL_REVISION) return { className: "quality-meanflow", label: "MF 4" };
  const labels = { turbo: "高速", fast: "バランス", quality: "高品質" } as const;
  return { className: `quality-${take.quality}`, label: labels[take.quality] };
}
