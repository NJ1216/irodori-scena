import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { api } from "../../api";
import type { DraftJob, LlmConnection, StudioProject } from "../../types";
import type { DraftComposerState } from "../studio/types";
import { DraftCastPicker, DraftCastSettingsTable, DraftContentFields } from "./DraftComposerForm";
import { DraftGenerationDialog, DraftResult } from "./DraftStatus";
import { draftCastSettingsRequest } from "./draftCastSettings";
import { displayedDraftProgress } from "./draftProgress";

type DraftViewProps = {
  project: StudioProject;
  connection: LlmConnection;
  job: DraftJob | null;
  busy: string | null;
  composer: DraftComposerState;
  onComposerChange: Dispatch<SetStateAction<DraftComposerState>>;
  onStartJob: (job: DraftJob) => void;
  onCancelJob: () => Promise<void>;
  onNotice: (text: string) => void;
  onBusy: (value: string | null) => void;
};

function generatedCharacters(job: DraftJob | null) {
  return job?.generatedCharacters ?? Math.max(0, job?.acceptedCharactersTotal ?? 0);
}

export function DraftView({ project, connection, job, busy, composer, onComposerChange, onStartJob, onCancelJob, onNotice, onBusy }: DraftViewProps) {
  const [elapsed, setElapsed] = useState(0);
  const generating = job?.status === "planning" || job?.status === "generating";
  const suggestingTheme = busy === "theme-suggestion";
  const selectedCharacters = project.characters.filter((character) => composer.selectedIds.includes(character.id));
  const targetCharacters = job?.targetCharacters || Math.max(160, Math.round(composer.minutes * 360 * project.settings.speechRate));
  const generated = generatedCharacters(job);
  const phaseElapsed = job ? Math.max(0, elapsed - Math.floor(((job.phaseStartedAt ?? job.startedAt) - job.startedAt) / 1000)) : elapsed;
  const progress = displayedDraftProgress(job, generated, targetCharacters, phaseElapsed);
  useEffect(() => {
    if (!generating || !job) return;
    const update = () => setElapsed(Math.floor((Date.now() - job.startedAt) / 1000));
    update();
    const timer = window.setInterval(update, 500);
    return () => window.clearInterval(timer);
  }, [generating, job]);
  const validate = () => {
    if (!composer.selectedIds.length) {
      onNotice("参加キャラクターを選んでください。");
      return false;
    }
    if (!connection.model.trim()) {
      onNotice("設定ページで既定のLLMモデルを選択してください。");
      return false;
    }
    return true;
  };
  const suggestTheme = async (mode: "random" | "detail") => {
    if (!validate()) return;
    onBusy("theme-suggestion");
    try {
      const result = await api.suggestTheme({ theme: mode === "random" ? "" : composer.theme, target_minutes: composer.minutes, character_ids: composer.selectedIds, cast_settings: draftCastSettingsRequest(composer.selectedIds, composer.castSettings) });
      onComposerChange((current) => ({ ...current, theme: result.theme }));
      onNotice("AIのテーマ案を入力欄へ反映しました。必要に応じて整えてください。");
    } catch (error) {
      onNotice(`テーマを提案できませんでした: ${(error as Error).message}`);
    } finally {
      onBusy(null);
    }
  };
  const generate = async () => {
    if (busy && !generating) return void onNotice("ほかの処理が完了してからAI台本を開始してください。");
    if (!validate()) return;
    setElapsed(0);
    onNotice("LLMに台本の全体構成を依頼しています…");
    const { selectedIds, minutes, theme, performance, simultaneousCues, overlappingSpeech, castSettings } = composer;
    try {
      onStartJob(
        await api.startAiJob({
          mode: "draft",
          character_ids: selectedIds,
          target_minutes: minutes,
          theme,
          speech_rate: project.settings.speechRate,
          line_gap: project.settings.lineGap ?? 0.7,
          performance_speech_rate_min: performance.speechRateMin,
          performance_speech_rate_max: performance.speechRateMax,
          performance_gap_min: performance.gapMin,
          performance_gap_max: performance.gapMax,
          allowed_emojis: performance.allowedEmojis,
          simultaneous_cues: selectedIds.length > 1 && simultaneousCues,
          overlapping_speech: selectedIds.length > 1 && overlappingSpeech,
          cast_settings: draftCastSettingsRequest(selectedIds, castSettings),
        }),
      );
    } catch (error) {
      onNotice(`台本を生成できませんでした: ${(error as Error).message}`);
    }
  };
  const toggleCast = (characterId: string) =>
    onComposerChange((current) => {
      if (current.selectedIds.includes(characterId)) return { ...current, selectedIds: current.selectedIds.filter((id) => id !== characterId) };
      if (current.selectedIds.length >= 8) {
        onNotice("AI台本では同時に選べるキャストは8人までです。");
        return current;
      }
      return { ...current, selectedIds: [...current.selectedIds, characterId] };
    });
  return (
    <section className="page draft-page">
      <div className="page-heading accent-heading">
        <p className="eyebrow type-eyebrow">AI SCRIPT DRAFT</p>
        <h1 className="type-display">AIに台本の下書きを頼む</h1>
        <p className="type-body">キャラクター設定を会話の個性に使い、本文・間・各行のト書きをまとめて提案します。</p>
      </div>
      <div className="draft-grid">
        <section className="panel surface-ai draft-composer">
          <DraftCastPicker characters={project.characters} selectedIds={composer.selectedIds} onToggle={toggleCast} />
          {selectedCharacters.length > 0 && (
            <>
              <DraftCastSettingsTable characters={selectedCharacters} composer={composer} onChange={onComposerChange} />
              <DraftContentFields composer={composer} connection={connection} generating={generating} suggestingTheme={suggestingTheme} onChange={onComposerChange} onSuggestTheme={(mode) => void suggestTheme(mode)} onGenerate={() => void generate()} />
            </>
          )}
        </section>
      </div>
      {generating && job && <DraftGenerationDialog job={job} elapsed={elapsed} generatedCharacters={generated} targetCharacters={targetCharacters} overallProgress={progress} onCancel={onCancelJob} />}
      {job && !generating && <DraftResult job={job} />}
    </section>
  );
}
