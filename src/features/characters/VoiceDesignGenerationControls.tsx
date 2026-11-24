import { EditableRangeControl } from "../shared/EditableRangeControl";
import type { CharactersViewModel } from "./useCharactersViewModel";

export function VoiceDesignGenerationControls({ model }: { model: CharactersViewModel }) {
  return (
    <section className="voice-design-generation-controls" aria-label="VoiceDesign生成設定">
      <EditableRangeControl label="基準話速" value={model.baselineSpeechRate} minimum={0.5} maximum={2} step={0.01} unit="倍" onChange={model.setBaselineSpeechRate} />
      {model.supportsRuntimeCfg && (
        <>
          <EditableRangeControl label="台詞への追従" technicalLabel="textCfg" value={model.voiceDesignTextCfg} minimum={0} maximum={10} step={0.1} onChange={model.setVoiceDesignTextCfg} />
          <EditableRangeControl label="基準ボイスへの追従" technicalLabel="voiceCfg" value={model.voiceDesignVoiceCfg} minimum={0} maximum={10} step={0.1} onChange={model.setVoiceDesignVoiceCfg} />
          <EditableRangeControl label="声の指定への追従" technicalLabel="captionCfg" value={model.voiceDesignCaptionCfg} minimum={0} maximum={10} step={0.1} onChange={model.setVoiceDesignCaptionCfg} />
        </>
      )}
    </section>
  );
}
