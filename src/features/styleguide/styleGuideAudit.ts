import baseCss from "../../styles/base.css?raw";
import characterPickerCss from "../../styles/character-picker.css?raw";
import charactersCss from "../../styles/characters.css?raw";
import draftCss from "../../styles/draft-and-settings.css?raw";
import notebookCss from "../../styles/notebook.css?raw";
import primitivesCss from "../../styles/primitives.css?raw";
import pronunciationCss from "../../styles/pronunciation.css?raw";
import scriptCss from "../../styles/script.css?raw";
import scriptActionsCss from "../../styles/script-actions.css?raw";
import shellCss from "../../styles/shell-and-draft.css?raw";
import { findUntokenizedCssValues, summarizeCssTokenAudit } from "./cssTokenAudit";

const styleSources = [
  ["基本画面", "base.css", baseCss],
  ["台本", "script.css", scriptCss],
  ["台本アクション", "script-actions.css", scriptActionsCss],
  ["キャスト選択", "character-picker.css", characterPickerCss],
  ["キャスト", "characters.css", charactersCss],
  ["AI台本・設定", "draft-and-settings.css", draftCss],
  ["キャストノート", "notebook.css", notebookCss],
  ["共通プリミティブ", "primitives.css", primitivesCss],
  ["読み辞書", "pronunciation.css", pronunciationCss],
  ["シェル", "shell-and-draft.css", shellCss],
] as const;

export const audit = styleSources.flatMap(([, source, css]) => findUntokenizedCssValues(css, source));
export const auditSummary = summarizeCssTokenAudit(audit);
