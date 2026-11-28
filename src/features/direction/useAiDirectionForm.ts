import { useMemo, useRef, useState } from "react";
import { api } from "../../api";
import type { DraftJob, StudioProject } from "../../types";
import type { ProjectEditSession, ProjectOperation } from "../studio/projectEditSession";
import { IRODORI_EMOJI_PALETTE } from "../shared/studio-utils";
import { buildDirectionLines, type RangeKey, type Removal, type Setting, type TakeMode } from "./aiDirectionLines";
import { useAiDirectionProgress } from "./useAiDirectionProgress";
import { useInlineValidation } from "../shared/useInlineValidation";

type CompleteHandler = (project: StudioProject, lineIds: string[], takeMode: TakeMode, operation: ProjectOperation) => void;

type Options = {
  project: StudioProject;
  projectSession: ProjectEditSession;
  onClose: () => void;
  onComplete: CompleteHandler;
  onNotice: (message: string) => void;
};

function useSettingToggles() {
  const [selected, setSelected] = useState<Record<Setting, boolean>>({ emoji: true, rate: true, gap: true, direction: true });
  const [removed, setRemoved] = useState<Record<Removal, boolean>>({ emoji: false, rate: false, gap: false, direction: false });
  const toggleDirectionMode = (key: Setting) => {
    if (selected[key]) {
      setSelected((value) => ({ ...value, [key]: false }));
      setRemoved((value) => ({ ...value, [key]: true }));
      return;
    }
    if (removed[key]) {
      setRemoved((value) => ({ ...value, [key]: false }));
      return;
    }
    setSelected((value) => ({ ...value, [key]: true }));
  };
  return { selected, removed, toggleDirectionMode };
}

function useRangeDrafts() {
  const [ranges, setRanges] = useState<Record<RangeKey, string>>({ rateMin: "0.85", rateMax: "1.35", gapMin: "0", gapMax: "5" });
  const setRange = (key: RangeKey, value: string) => setRanges((current) => ({ ...current, [key]: value }));
  return { ranges, setRange };
}

export function useAiDirectionForm({ project, projectSession, onClose, onComplete, onNotice }: Options) {
  const lines = useMemo(() => buildDirectionLines(project), [project]);
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(Math.max(0, lines.length - 1));
  const [overwriteExisting, setOverwriteExisting] = useState(false);
  const { selected, removed, toggleDirectionMode } = useSettingToggles();
  const [castEmoji, setCastEmoji] = useState<Record<string, boolean>>({});
  const [allowed, setAllowed] = useState<string[]>(IRODORI_EMOJI_PALETTE.map(([emoji]) => emoji));
  const { ranges, setRange: setRangeDraft } = useRangeDrafts();
  const validation = useInlineValidation();
  const setRange = (key: RangeKey, value: string) => {
    setRangeDraft(key, value);
    validation.clear(key.startsWith("rate") ? "rate" : "gap");
  };
  const [takeMode, setTakeMode] = useState<TakeMode>("append");
  const [job, setJob] = useState<DraftJob | null>(null);
  const running = Boolean(job && ["planning", "generating"].includes(job.status));
  const operation = useRef<ProjectOperation | null>(null);
  useAiDirectionProgress({ running, job, setJob, operation, projectSession, takeMode, onClose, onComplete, onNotice });
  const targetCastIds = [...new Set(lines.slice(start, end + 1).map((line) => line.characterId))];
  const targetCasts = targetCastIds.map((id) => project.characters.find((character) => character.id === id)).filter((character) => character !== undefined);
  const emojiActive = selected.emoji && targetCastIds.some((id) => castEmoji[id] ?? true);
  const parsedRanges = [ranges.rateMin, ranges.rateMax, ranges.gapMin, ranges.gapMax].map(Number);
  const validRange = (min: string, max: string) => min.trim() !== "" && max.trim() !== "" && Number.isFinite(Number(min)) && Number.isFinite(Number(max)) && Number(min) <= Number(max);
  const invalidRange = selected.rate && !validRange(ranges.rateMin, ranges.rateMax) ? "rate" : selected.gap && !validRange(ranges.gapMin, ranges.gapMax) ? "gap" : null;
  const execute = async () => {
    if (invalidRange) {
      validation.report("話速と発話間隔は、最小値が最大値以下になる数値で入力してください。", invalidRange);
      return;
    }
    try {
      const result = await projectSession.runServer((token) => {
        operation.current = token;
        return api.startAiJob({
          mode: "direction",
          line_ids: lines.slice(start, end + 1).map((line) => line.id),
          emoji_expressions: emojiActive,
          cast_settings: selected.emoji ? Object.fromEntries(targetCastIds.map((id) => [id, { emoji_expressions: castEmoji[id] ?? true }])) : {},
          direction_speech_rate: selected.rate,
          gap_seconds: selected.gap,
          stage_direction: selected.direction,
          remove_emoji_expressions: removed.emoji,
          remove_speech_rate: removed.rate,
          remove_gap_seconds: removed.gap,
          remove_stage_direction: removed.direction,
          overwrite_existing: overwriteExisting,
          allowed_emojis: allowed,
          speech_rate_min: selected.rate ? parsedRanges[0] : 0.85,
          speech_rate_max: selected.rate ? parsedRanges[1] : 1.35,
          gap_min: selected.gap ? parsedRanges[2] : 0,
          gap_max: selected.gap ? parsedRanges[3] : 5,
        });
      });
      if (result) setJob(result);
    } catch (error) {
      onNotice(`AI演出を開始できません: ${(error as Error).message}`);
    }
  };
  const enabled = emojiActive || selected.rate || selected.gap || selected.direction || Object.values(removed).some(Boolean);
  return {
    lines,
    start,
    setStart,
    end,
    setEnd,
    overwriteExisting,
    setOverwriteExisting,
    selected,
    removed,
    toggleDirectionMode,
    castEmoji,
    setCastEmoji,
    allowed,
    setAllowed,
    ranges,
    setRange,
    takeMode,
    setTakeMode,
    job,
    setJob,
    running,
    targetCasts,
    emojiActive,
    rangeError: validation.fieldError("rate") || validation.fieldError("gap"),
    rangeErrorField: validation.fieldError("rate") ? ("rate" as const) : validation.fieldError("gap") ? ("gap" as const) : null,
    execute,
    enabled,
  };
}
