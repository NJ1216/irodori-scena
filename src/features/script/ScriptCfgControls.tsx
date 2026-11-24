import type { StudioProject } from "../../types";
import { EditableRangeControl } from "../shared/EditableRangeControl";
import { DoubleChevron } from "../shared/DoubleChevron";

export function ScriptCfgControls({ settings, onSettings }: { settings: StudioProject["settings"]; onSettings: (patch: Partial<StudioProject["settings"]>) => void }) {
  return (
    <details className="script-cfg-controls">
      <summary aria-label="CFG設定を開閉">
        <DoubleChevron className="script-cfg-chevron" />
      </summary>
      <div className="script-cfg-control-list">
        <EditableRangeControl label="セリフへの追従" technicalLabel="textCfg" value={settings.textCfg ?? 3} minimum={0} maximum={10} step={0.1} onChange={(textCfg) => onSettings({ textCfg })} />
        <EditableRangeControl label="基準ボイスへの追従" technicalLabel="voiceCfg" value={settings.voiceCfg ?? 5} minimum={0} maximum={10} step={0.1} onChange={(voiceCfg) => onSettings({ voiceCfg })} />
        <EditableRangeControl label="声の指定への追従" technicalLabel="captionCfg" value={settings.captionCfg ?? 3} minimum={0} maximum={10} step={0.1} onChange={(captionCfg) => onSettings({ captionCfg })} />
      </div>
    </details>
  );
}
