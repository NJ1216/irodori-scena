import { revealVoiceSampleEmojis } from "./voiceSampleEmojiVisibility";
import { useRef, useState } from "react";
import type { VoiceDesignEmotion } from "../../types";
import type { CharactersViewModel } from "./useCharactersViewModel";
import { AudioPlaybackBar, type DecodedAudioPlaybackControl } from "./AudioPlaybackBar";
import { EmojiPalette } from "../script/EmojiPalette";
import { DialogFooter, DialogHeader } from "../shared/overlays";
import { VoiceCandidateActionGroup } from "./VoiceCandidateActionGroup";
import { CharacterMemoField } from "./CharacterMemoField";
import { VoiceDesignForm, VoiceDesignTip } from "./VoiceDesignForm";
import { VoiceDesignGenerationControls } from "./VoiceDesignGenerationControls";
import { ReferenceLengthNotice } from "./ReferenceLengthNotice";
const emotions: Array<[VoiceDesignEmotion, string]> = [
  ["normal", "普通"],
  ["joy", "喜"],
  ["anger", "怒"],
  ["sorrow", "哀"],
  ["delight", "楽"],
];
const choiceLabel = (index: number) => String.fromCharCode(65 + index);
const auditionTextTips = ["実際にそのキャストが話しているような口調の台詞を用意してください。", "話し方の特徴が伝わり、狙った声を生成しやすくなります。"];

export function CandidateChoices({
  candidates,
  label,
  selectedId,
  generatingCount = 0,
  onSelect,
  onPlay,
  onPause,
  onEnded,
}: {
  candidates: CharactersViewModel["project"]["candidates"];
  label: string;
  selectedId?: string;
  generatingCount?: number;
  onSelect: (candidateId: string) => void;
  onPlay: (audio: DecodedAudioPlaybackControl) => void;
  onPause: (audio: DecodedAudioPlaybackControl) => void;
  onEnded: (audio: DecodedAudioPlaybackControl) => void;
}) {
  return (
    <div className={`voice-candidate-choices${generatingCount > 0 ? " is-generating" : ""}`} aria-label={generatingCount > 0 ? `${label}候補を生成中` : undefined} aria-busy={generatingCount > 0 || undefined}>
      {candidates.map((candidate, index) => {
        const choice = choiceLabel(index);
        return (
          <div className="voice-candidate-choice" key={candidate.id}>
            <AudioPlaybackBar compact compactLabel={choice} selected={selectedId === candidate.id} label={`${label}候補 ${choice}`} src={candidate.audioUrl} onActivate={() => onSelect(candidate.id)} onPlay={onPlay} onEnded={onEnded} onPause={onPause} />
          </div>
        );
      })}
      {Array.from({ length: generatingCount }, (_, index) => {
        const choice = choiceLabel(candidates.length + index);
        return (
          <div className="voice-candidate-choice is-generating" key={`generating-${choice}`}>
            <button type="button" disabled aria-label={`${label}候補 ${choice}を生成中`}>
              <span>{choice}</span>
              <svg className="voice-candidate-generating-border" viewBox="0 0 28 28" aria-hidden="true">
                <rect x="1" y="1" width="26" height="26" rx="5" pathLength="100" />
              </svg>
            </button>
          </div>
        );
      })}
    </div>
  );
}

function EmotionCandidateActions({ model, emotion, label, hasCandidates, onGenerate }: { model: CharactersViewModel; emotion: VoiceDesignEmotion; label: string; hasCandidates: boolean; onGenerate: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const { busy, baselineCandidateId, emotionCandidateIds, setEmotionCandidateIds, onClearCandidateScope } = model;
  return (
    <>
      <input
        ref={input}
        className="voice-design-reference-input"
        type="file"
        accept="audio/wav,.wav"
        onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          if (file) void model.importEmotionVoiceDesignReference(file, emotion);
          event.currentTarget.value = "";
        }}
      />
      <VoiceCandidateActionGroup
        label={label}
        disabled={Boolean(busy)}
        generating={busy === "candidates"}
        clearDisabled={!hasCandidates}
        onGenerate={onGenerate}
        onReference={() => input.current?.click()}
        onClear={() => {
          if (baselineCandidateId)
            void onClearCandidateScope("emotion", { emotion, referenceCandidateId: baselineCandidateId }).then((cleared) => {
              if (cleared) setEmotionCandidateIds({ ...emotionCandidateIds, [emotion]: undefined });
            });
        }}
      />
    </>
  );
}

function EmotionStep({ model }: { model: CharactersViewModel }) {
  const {
    project,
    baselineCandidateId,
    emotionTexts,
    setEmotionTexts,
    suggestedEmotionTexts,
    setSuggestedEmotionTexts,
    emotionCandidateIds,
    setEmotionCandidateIds,
    generateEmotion,
    keywords,
    voiceDesignValue,
    count,
    baselineSpeechRate,
    voiceDesignTextCfg,
    voiceDesignVoiceCfg,
    voiceDesignCaptionCfg,
    supportsRuntimeCfg,
    beginCandidatePlayback,
    endCandidatePlayback,
  } = model;
  if (!baselineCandidateId) return null;
  return (
    <section className="voice-design-emotions voice-design-step">
      <div className="candidate-list-heading">
        <h3 className="ai-direction-step">
          <span>3</span>感情を追加
        </h3>
      </div>
      {emotions.map(([emotion, label]) => {
        const clips = project.candidates.filter((candidate) => candidate.kind === "emotion" && candidate.emotion === emotion && candidate.referenceCandidateId === baselineCandidateId);
        const textareaId = `voice-design-${emotion}-text`;
        return (
          <div className="voice-emotion" key={emotion}>
            <span className="voice-emotion-label">
              <label htmlFor={textareaId}>{label}の台詞</label>
              <EmotionCandidateActions
                model={model}
                emotion={emotion}
                label={label}
                hasCandidates={clips.length > 0}
                onGenerate={() =>
                  void generateEmotion(emotion, keywords, voiceDesignValue, count, {
                    speechRate: baselineSpeechRate,
                    ...(supportsRuntimeCfg ? { textCfg: voiceDesignTextCfg, voiceCfg: voiceDesignVoiceCfg, captionCfg: voiceDesignCaptionCfg } : {}),
                  })
                }
              />
            </span>
            <textarea
              className={suggestedEmotionTexts.has(emotion) ? "is-ai-suggested" : ""}
              id={textareaId}
              value={emotionTexts[emotion]}
              onChange={(event) => {
                setEmotionTexts({ ...emotionTexts, [emotion]: event.target.value });
                setSuggestedEmotionTexts((current) => {
                  const next = new Set(current);
                  next.delete(emotion);
                  return next;
                });
              }}
            />
            <CandidateChoices candidates={clips} label={label} selectedId={emotionCandidateIds[emotion]} onSelect={(candidateId) => setEmotionCandidateIds({ ...emotionCandidateIds, [emotion]: candidateId })} onPlay={beginCandidatePlayback} onPause={endCandidatePlayback} onEnded={endCandidatePlayback} />
          </div>
        );
      })}
    </section>
  );
}

function ReplaceReferenceAction({ model, onSaved }: { model: CharactersViewModel; onSaved: () => void }) {
  const { busy, baselineCandidateId, canReplaceVoiceDesign, name, profile, keywords, voiceDesignValue, referenceVoiceTarget, saveDesignedVoice } = model;
  if (!referenceVoiceTarget || !baselineCandidateId) return null;
  return (
    <button
      className="button-primary primary"
      type="button"
      disabled={busy === "save-voice-design" || !canReplaceVoiceDesign}
      onClick={() =>
        void saveDesignedVoice({ name, profile, voiceKeywords: keywords, voiceDesign: voiceDesignValue, characterId: referenceVoiceTarget.id }).then((saved) => {
          if (saved) onSaved();
        })
      }
    >
      参照ボイスを置き換える
    </button>
  );
}

function EmotionOption({ model }: { model: CharactersViewModel }) {
  const { baselineCandidateId, includeEmotions, setIncludeEmotions } = model;
  if (!baselineCandidateId) return null;
  return (
    <section className="voice-design-emotion-option">
      <label className="voice-design-emotion-toggle">
        <input type="checkbox" checked={includeEmotions} onChange={(event) => setIncludeEmotions(event.target.checked)} />
        <span>感情参照を追加する（任意）</span>
      </label>
    </section>
  );
}

function VoiceDesignSaveStep({ model }: { model: CharactersViewModel }) {
  const { baselineCandidateId, includeEmotions, name, setName, profile, setProfile, referenceVoiceTarget } = model;
  if (!baselineCandidateId || referenceVoiceTarget) return null;
  return (
    <section className="audition-list voice-design-step">
      <h3 className="ai-direction-step">
        <span>{includeEmotions ? 4 : 3}</span>キャストとして保存
      </h3>
      <label>
        キャスト名
        <input value={name} aria-invalid={!name.trim()} onChange={(event) => setName(event.target.value)} required />
      </label>
      <CharacterMemoField value={profile} onChange={setProfile} />
    </section>
  );
}

function SaveVoiceDesignAction({ model, onSaved }: { model: CharactersViewModel; onSaved: () => void }) {
  const { busy, baselineCandidateId, canSaveVoiceDesign, name, profile, keywords, voiceDesignValue, referenceVoiceTarget, saveDesignedVoice } = model;
  if (!baselineCandidateId || referenceVoiceTarget) return null;
  return (
    <button
      className="primary"
      type="button"
      disabled={busy === "save-voice-design" || !canSaveVoiceDesign}
      onClick={() =>
        void saveDesignedVoice({ name, profile, voiceKeywords: keywords, voiceDesign: voiceDesignValue }).then((saved) => {
          if (saved) onSaved();
        })
      }
    >
      参照ボイスを保存
    </button>
  );
}

function BaselineSetupStep({ model, collapsed, hasGenerated, onToggle }: { model: CharactersViewModel; collapsed: boolean; hasGenerated: boolean; onToggle: () => void }) {
  const { busy, suggestingVoice, setVoiceSuggestionOpen, voiceDesignValue, setVoiceDesignValue, voiceDesignSuggestedFields, sampleText, setSampleText, sampleTextSuggested, setSampleTextSuggested, sampleTextInput, insertSampleTextEmoji } = model;
  return (
    <section className={`voice-design-step voice-design-setup-step${collapsed ? " is-collapsed" : ""}`}>
      <div className="voice-design-step-heading">
        <div className="voice-design-step-title">
          <h3 className="ai-direction-step">
            <span>1</span>基準ボイスを選ぶ
          </h3>
          <button type="button" className="voice-design-step-disclosure" aria-expanded={!collapsed} aria-label={collapsed ? "基準ボイスの設定を展開" : "基準ボイスの設定を折りたたむ"} title={collapsed ? "基準ボイスの設定を展開" : "基準ボイスの設定を折りたたむ"} onClick={onToggle}>
            <svg viewBox="0 0 16 12" aria-hidden="true">
              <path d="m3 2 5 4 5-4" />
              <path d="m3 6 5 4 5-4" />
            </svg>
          </button>
        </div>
        <button type="button" className="secondary ai-action-button voice-suggestion-button" disabled={busy === "candidates" || suggestingVoice} onClick={() => setVoiceSuggestionOpen(true)}>
          {hasGenerated ? "✦ 再びAIに声の設計を相談" : "✦ AIに声の設計を相談"}
        </button>
      </div>
      <div className="voice-design-setup-content" aria-hidden={collapsed} inert={collapsed}>
        <div className="voice-design-setup-content-body">
          <VoiceDesignForm value={voiceDesignValue} suggested={voiceDesignSuggestedFields} onChange={setVoiceDesignValue} />
          <div className={`voice-design-field${sampleTextSuggested ? " is-ai-suggested" : ""}`}>
            <span className="voice-design-field-label">
              <label htmlFor="voice-design-audition-text">基準用の試聴台詞</label>
              <VoiceDesignTip label="基準用の試聴台詞" paragraphs={auditionTextTips} />
            </span>
            <textarea
              id="voice-design-audition-text"
              ref={sampleTextInput}
              value={sampleText}
              onChange={(event) => {
                setSampleText(event.target.value);
                setSampleTextSuggested(false);
              }}
              placeholder="誰にでも自然な短い一〜二文"
            />
          </div>
          <details className="voice-sample-emoji-inserter" onToggle={(event) => revealVoiceSampleEmojis(event.currentTarget)}>
            <summary>表情EMOJIを挿入</summary>
            <EmojiPalette onInsert={insertSampleTextEmoji} />
          </details>
        </div>
      </div>
    </section>
  );
}

function BaselineAuditionStep({ model, sectionRef, generating, onGenerate, onClear }: { model: CharactersViewModel; sectionRef: React.RefObject<HTMLElement | null>; generating: boolean; onGenerate: () => void; onClear: () => void }) {
  const { project, busy, suggestingVoice, count, setCount, referenceInput, importVoiceDesignReference, baselineCandidateId, setBaselineCandidateId, setEmotionCandidateIds, beginCandidatePlayback, endCandidatePlayback } = model;
  const baselines = project.candidates.filter((candidate) => (candidate.kind ?? "baseline") === "baseline");
  return (
    <section ref={sectionRef} className="voice-design-step voice-design-audition-step">
      <h3 className="ai-direction-step">
        <span>2</span>AUDITION
      </h3>
      <VoiceDesignGenerationControls model={model} />
      <section className="audition-list">
        <div className="candidate-list-heading">
          <input
            ref={referenceInput}
            className="voice-design-reference-input"
            type="file"
            accept="audio/wav,.wav"
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              if (file) void importVoiceDesignReference(file);
              event.currentTarget.value = "";
            }}
          />
          <VoiceCandidateActionGroup
            label="基準ボイス"
            generateLabel="基準ボイス候補をつくる"
            referenceLabel="参照ボイスを読み込む"
            clearLabel="基準候補を消去"
            disabled={Boolean(busy) || suggestingVoice}
            generating={generating}
            clearDisabled={baselines.length === 0}
            onGenerate={onGenerate}
            onReference={() => referenceInput.current?.click()}
            onClear={onClear}
          />
          <label className="candidate-count-field">
            <span className="visually-hidden">候補数</span>
            <select value={count} onChange={(event) => setCount(Number(event.target.value))}>
              <option value={3}>3候補</option>
              <option value={5}>5候補</option>
              <option value={10}>10候補</option>
            </select>
          </label>
        </div>
        <CandidateChoices
          candidates={baselines}
          label="基準"
          selectedId={baselineCandidateId ?? undefined}
          generatingCount={generating ? count : 0}
          onSelect={(candidateId) => {
            setBaselineCandidateId(candidateId);
            setEmotionCandidateIds({});
          }}
          onPlay={beginCandidatePlayback}
          onPause={endCandidatePlayback}
          onEnded={endCandidatePlayback}
        />
        <EmotionOption model={model} />
      </section>
    </section>
  );
}

function WavImportDialog({ model }: { model: CharactersViewModel }) {
  const { busy, fileInput, importName, importProfile, referenceFile, setImportName, setImportProfile, setReferenceFile, setWavImportOpen, importWav } = model;
  return (
    <div className="modal-backdrop">
      <form className="modal wav-import-modal" onSubmit={(event) => void importWav(event)}>
        <DialogHeader eyebrow="REFERENCE WAV" title="手元のWAVを登録" description="参照に使う音声とキャストの基本情報を登録します。" />
        <div className="wav-import-fields">
          <label className="file-picker">
            <input ref={fileInput} type="file" accept="audio/wav,.wav" onChange={(event) => setReferenceFile(event.target.files?.[0] ?? null)} />
            <span>{referenceFile ? referenceFile.name : "WAVファイルを選択"}</span>
            <small>標準WAV・25 MBまで</small>
          </label>
          <label className="wav-import-field">
            キャラクター名
            <input value={importName} onChange={(event) => setImportName(event.target.value)} required />
          </label>
          <CharacterMemoField className="wav-import-field" value={importProfile} onChange={setImportProfile} placeholder="性格や話し方など、声と一緒に残したい設定" />
        </div>
        <DialogFooter>
          <button type="button" onClick={() => setWavImportOpen(false)}>
            キャンセル
          </button>
          <button className="primary" disabled={busy === "import-reference"}>
            {busy === "import-reference" ? "登録中…" : "この声をキャストに登録"}
          </button>
        </DialogFooter>
      </form>
    </div>
  );
}

export function CharacterVoiceDialogs({ model }: { model: CharactersViewModel }) {
  const [baselineSetupCollapsed, setBaselineSetupCollapsed] = useState(false);
  const [baselineSetupCollapsible, setBaselineSetupCollapsible] = useState(false);
  const [baselineGenerating, setBaselineGenerating] = useState(false);
  const auditionStep = useRef<HTMLElement>(null);
  const { connection, onClearCandidateScope, resetVoiceDesignSession, voiceSuggestionOpen, setVoiceSuggestionOpen, voiceDesignOpen, wavImportOpen, sourceKeywords, setSourceKeywords, suggestingVoice, generate, suggestVoiceDesign, closeVoiceDesign } = model;
  const finishVoiceDesign = () => {
    setBaselineSetupCollapsed(false);
    setBaselineSetupCollapsible(false);
    resetVoiceDesignSession();
    closeVoiceDesign();
  };
  const dismissVoiceDesign = () => {
    setBaselineSetupCollapsed(false);
    setBaselineSetupCollapsible(false);
    closeVoiceDesign();
  };
  async function generateBaselineCandidates() {
    setBaselineGenerating(true);
    try {
      const generated = await generate();
      if (!generated) return;
      setBaselineSetupCollapsible(true);
      setBaselineSetupCollapsed(true);
      requestAnimationFrame(() => auditionStep.current?.scrollIntoView({ block: "nearest" }));
    } finally {
      setBaselineGenerating(false);
    }
  }
  return (
    <>
      {voiceDesignOpen && (
        <div className="modal-backdrop">
          <section className="modal voice-design-modal" role="dialog" aria-modal="true" aria-label="声の候補をつくる">
            <DialogHeader eyebrow="VOICE DESIGN" title="キャストの音声をデザインする" />
            <div className={`voice-design-workspace${model.includeEmotions ? " has-emotions" : ""}`}>
              <div className="voice-design-baseline-panel">
                <BaselineSetupStep model={model} collapsed={baselineSetupCollapsed} hasGenerated={baselineSetupCollapsible} onToggle={() => setBaselineSetupCollapsed((current) => !current)} />
                <BaselineAuditionStep
                  model={model}
                  sectionRef={auditionStep}
                  generating={baselineGenerating}
                  onGenerate={() => void generateBaselineCandidates()}
                  onClear={() =>
                    void onClearCandidateScope("baseline").then((cleared) => {
                      if (!cleared) return;
                      resetVoiceDesignSession();
                      setBaselineSetupCollapsed(false);
                      setBaselineSetupCollapsible(false);
                    })
                  }
                />
                <VoiceDesignSaveStep model={model} />
              </div>
              {model.includeEmotions && model.combinedVoiceDesignUnavailableReason && <p className="warning-text">{model.combinedVoiceDesignUnavailableReason} caption単独のVoiceDesignは利用できます。</p>}
              {model.includeEmotions && !model.combinedVoiceDesignUnavailableReason && <EmotionStep model={model} />}
              {model.includeEmotions && <ReferenceLengthNotice candidates={model.project.candidates} baselineCandidateId={model.baselineCandidateId} emotionCandidateIds={model.emotionCandidateIds} />}
            </div>
            <DialogFooter>
              <button type="button" onClick={dismissVoiceDesign}>
                キャンセル
              </button>
              <SaveVoiceDesignAction model={model} onSaved={finishVoiceDesign} />
              <ReplaceReferenceAction model={model} onSaved={finishVoiceDesign} />
            </DialogFooter>
          </section>
        </div>
      )}
      {wavImportOpen && <WavImportDialog model={model} />}
      {voiceSuggestionOpen && (
        <div className="modal-backdrop">
          <form className="modal voice-suggestion-modal" onSubmit={(event) => void suggestVoiceDesign(event)}>
            <DialogHeader eyebrow="VOICE DESIGN ASSIST" title="AIに声の設計を相談" description="声の指定、基準用台詞、普通・喜・怒・哀・楽の短い台詞を提案します。生成後も編集できます。" />
            <label>
              声のアイデア
              <textarea value={sourceKeywords} onChange={(event) => setSourceKeywords(event.target.value)} autoFocus />
            </label>
            <p className="connection-hint">接続先：{connection.model || "設定ページで選択してください"}</p>
            <DialogFooter>
              <button type="button" disabled={suggestingVoice} onClick={() => setVoiceSuggestionOpen(false)}>
                キャンセル
              </button>
              <button className="primary ai-action-button" disabled={suggestingVoice}>
                {suggestingVoice ? "声を設計中…" : "声の設計を提案"}
              </button>
            </DialogFooter>
          </form>
        </div>
      )}
    </>
  );
}
