import { useMemo, useState } from "react";
import type { StudioProject } from "../../types";
import { draftCastSettingsFor } from "../draft/draftCastSettings";
import { IRODORI_EMOJI_PALETTE } from "../shared/studio-utils";
import type { DraftCastSettings, DraftPerformanceSettings, LineAssistantTarget } from "../studio/types";
import { applicableCharacterIds, enabledSimultaneousCues, initialCharacterIds, requiresSimultaneousCues, selectedProjectLines, selectedTargetLines, selectionIsSparse } from "./lineAssistantModel";
import type { RewriteMode, TargetKind } from "./ScriptAssistantSettings";
import type { ScriptAssistantJob } from "./scriptAssistantTypes";

const DEFAULT_PERFORMANCE: DraftPerformanceSettings = { speechRateMin: 0.85, speechRateMax: 1.35, gapMin: -2, gapMax: 5, allowedEmojis: IRODORI_EMOJI_PALETTE.map(([emoji]) => emoji) };

export type LineAssistantForm = ReturnType<typeof useLineAssistantForm>;

/** Owns the line assistant's editable settings, the running job, and the values derived from them. */
export function useLineAssistantForm(project: StudioProject, target: LineAssistantTarget) {
  const [targetLineIds, setTargetLineIds] = useState(target.kind === "rewrite" ? target.lineIds : []);
  const currentTarget = useMemo(() => (target.kind === "rewrite" ? ({ ...target, lineIds: targetLineIds } as LineAssistantTarget) : target), [target, targetLineIds]);
  const targetLines = useMemo(() => selectedProjectLines(project, currentTarget), [project, currentTarget]);
  const displayedTargetLines = useMemo(() => selectedTargetLines(project, currentTarget), [project, currentTarget]);
  const participantIds = useMemo(() => Array.from(new Set(project.scenes.flatMap((scene) => scene.lines.map((line) => line.characterId).filter(Boolean)))), [project]);
  const requiredSpeakerIds = useMemo(() => Array.from(new Set(targetLines.map((line) => line.characterId))), [targetLines]);
  const [rewriteMode, setRewriteMode] = useState<RewriteMode>("paraphrase");
  const [characterIds, setCharacterIds] = useState(initialCharacterIds(participantIds, requiredSpeakerIds));
  const [targetKind, setTargetKind] = useState<TargetKind>("lines");
  const [lineCount, setLineCount] = useState(String(Math.max(1, targetLines.length)));
  const [minutes, setMinutes] = useState("0.5");
  const [instruction, setInstruction] = useState("");
  const [castSettings, setCastSettings] = useState<Record<string, DraftCastSettings>>({});
  const [simultaneousCues, setSimultaneousCues] = useState(true);
  const [overlappingSpeech, setOverlappingSpeech] = useState(true);
  const [performance, setPerformance] = useState<DraftPerformanceSettings>(DEFAULT_PERFORMANCE);
  const [job, setJob] = useState<ScriptAssistantJob | null>(null);
  const [acceptedRows, setAcceptedRows] = useState(new Set<string>());
  const [acceptedGroups, setAcceptedGroups] = useState(new Set<string>());
  const sparse = selectionIsSparse(project, targetLineIds);
  const operation = target.kind === "insert" ? "insert" : rewriteMode;
  const castComposition = operation === "cast-compose";
  const castCompositionCharacterIds = applicableCharacterIds(operation, characterIds, requiredSpeakerIds);

  const changeCastSetting = (id: string, patch: Partial<DraftCastSettings>) => setCastSettings((current) => ({ ...current, [id]: { ...draftCastSettingsFor(current, id), ...patch } }));
  const changeTargetLineIds = (ids: string[]) => {
    setLineCount((current) => (current === String(targetLines.length) ? String(ids.length) : current));
    setTargetLineIds(ids);
  };
  const changeRewriteMode = (next: RewriteMode) => {
    setRewriteMode(next);
    if (next === "cast-compose") setCharacterIds(requiredSpeakerIds);
  };

  return {
    targetLines,
    displayedTargetLines,
    requiredSpeakerIds,
    rewriteMode,
    characterIds,
    targetKind,
    lineCount,
    minutes,
    instruction,
    castSettings,
    simultaneousCues,
    overlappingSpeech,
    performance,
    job,
    acceptedRows,
    acceptedGroups,
    sparse,
    operation,
    castComposition,
    castCompositionCharacterIds,
    fixedCount: target.kind === "rewrite" && (rewriteMode !== "rewrite" || sparse),
    simultaneousCuesEnabled: enabledSimultaneousCues(operation, sparse, characterIds.length, simultaneousCues),
    simultaneousRequired: requiresSimultaneousCues(operation, instruction),
    effectiveTargetLines: castComposition ? targetLines.filter((line) => castCompositionCharacterIds.includes(line.characterId)) : targetLines,
    settingsCharacters: castComposition ? project.characters.filter((character) => requiredSpeakerIds.includes(character.id)) : project.characters,
    setCharacterIds,
    setTargetKind,
    setLineCount,
    setMinutes,
    setInstruction,
    setSimultaneousCues,
    setOverlappingSpeech,
    setPerformance,
    setJob,
    setAcceptedRows,
    setAcceptedGroups,
    changeCastSetting,
    changeTargetLineIds,
    changeRewriteMode,
  };
}
