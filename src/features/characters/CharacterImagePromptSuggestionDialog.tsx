import { createContext, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { CharactersViewModel } from "./useCharactersViewModel";
import { ACCESSORY_GROUPS, prioritizedAppearanceOptions } from "./imagePromptAppearanceOptions";
import { PROMPT_COLORS } from "./imagePromptColors";
import { DialogFooter, DialogHeader } from "../shared/overlays";
import { DropdownIndicator } from "../shared/DropdownIndicator";
import { EXPRESSION_GROUPS } from "./imagePromptExpressions";
import { OCCUPATION_GROUPS } from "./imagePromptOccupations";
import * as options from "./imagePromptOptionCatalog";

const PromptMenuContext = createContext<{ active: string | null; setActive: (value: string | null) => void } | null>(null);

function PromptMenuPortal({ anchor, grouped = false, onClose, children }: { anchor: HTMLElement; grouped?: boolean; onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const bounds = anchor.getBoundingClientRect();
  const mainWidth = grouped ? 160 : bounds.width;
  const combinedWidth = grouped ? mainWidth + 230 : mainWidth;
  const flipped = bounds.left + combinedWidth > window.innerWidth - 12;
  const menuHeight = 300;
  const above = window.innerHeight - bounds.bottom < 180 && bounds.top > window.innerHeight - bounds.bottom;
  const top = above ? Math.max(12, bounds.top - menuHeight - 4) : Math.max(12, Math.min(bounds.bottom + 4, window.innerHeight - menuHeight - 12));
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node) && !anchor.contains(event.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [anchor, onClose]);
  return createPortal(
    <div ref={ref} className={`image-prompt-portal-menu${flipped ? " is-flipped" : ""}`} style={{ left: flipped ? bounds.right - mainWidth : bounds.left, top, width: mainWidth }}>
      {children}
    </div>,
    document.body,
  );
}

function PromptCombobox({ label, value, choices, groups, descriptions, onChange }: { label: string; value: string; choices?: readonly string[]; groups?: readonly { label: string; options: readonly string[] }[]; descriptions?: Readonly<Record<string, string>>; onChange: (value: string) => void }) {
  const menus = useContext(PromptMenuContext);
  const open = menus?.active === label;
  const [activeGroup, setActiveGroup] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<HTMLDivElement | null>(null);
  const setOpen = (next: boolean) => menus?.setActive(next ? label : null);
  const optionButton = (option: string) => (
    <button
      key={option}
      type="button"
      role="option"
      aria-selected={value === option}
      title={descriptions?.[option]}
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => {
        onChange(option);
        setOpen(false);
      }}
    >
      {option}
    </button>
  );
  const selectedGroup = groups?.find((group) => group.label === activeGroup);
  return (
    <label className="image-prompt-combobox">
      {label}
      <div>
        <input
          value={value}
          onFocus={(event) => {
            setAnchor(event.currentTarget.parentElement as HTMLDivElement);
            setOpen(true);
          }}
          onChange={(event) => {
            setAnchor(event.currentTarget.parentElement as HTMLDivElement);
            onChange(event.target.value);
            setOpen(true);
          }}
          placeholder="指定無し"
        />
        <button
          type="button"
          aria-label={`${label}の候補を表示`}
          aria-expanded={open}
          onMouseDown={(event) => event.preventDefault()}
          onClick={(event) => {
            setAnchor(event.currentTarget.parentElement as HTMLDivElement);
            setOpen(!open);
          }}
        >
          <DropdownIndicator />
        </button>
        {open && anchor && (
          <PromptMenuPortal anchor={anchor} grouped={Boolean(groups)} onClose={() => setOpen(false)}>
            <div className={`image-prompt-combobox-menu is-portaled${groups ? " is-grouped" : ""}`} role={groups ? "menu" : "listbox"}>
              {groups ? (
                <>
                  {groups.map((group) => (
                    <button
                      key={group.label}
                      className="image-prompt-group-trigger"
                      type="button"
                      aria-haspopup="listbox"
                      aria-expanded={activeGroup === group.label}
                      onMouseDown={(event) => event.preventDefault()}
                      onMouseEnter={() => setActiveGroup(group.label)}
                      onFocus={() => setActiveGroup(group.label)}
                      onClick={() => setActiveGroup(group.label)}
                    >
                      {group.label}
                      <span aria-hidden="true">›</span>
                    </button>
                  ))}
                  {selectedGroup && (
                    <div className="image-prompt-expression-submenu" role="listbox" aria-label={selectedGroup.label}>
                      {selectedGroup.options.map(optionButton)}
                    </div>
                  )}
                </>
              ) : (
                choices?.map(optionButton)
              )}
            </div>
          </PromptMenuPortal>
        )}
      </div>
    </label>
  );
}

export function PromptMultiSelect({ label, value, choices, groups, onChange }: { label: string; value: string[]; choices?: readonly string[]; groups?: readonly { label: string; options: readonly string[] }[]; onChange: (value: string[]) => void }) {
  const menus = useContext(PromptMenuContext);
  const [standaloneOpen, setStandaloneOpen] = useState(false);
  const [activeGroup, setActiveGroup] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<HTMLButtonElement | null>(null);
  const open = menus ? menus.active === label : standaloneOpen;
  const setOpen = (next: boolean) => (menus ? menus.setActive(next ? label : null) : setStandaloneOpen(next));
  const toggle = (option: string) => onChange(value.includes(option) ? value.filter((item) => item !== option) : [...value, option]);
  const selectedGroup = groups?.find((group) => group.label === activeGroup);
  const optionCheckbox = (option: string) => (
    <label key={option}>
      <input type="checkbox" checked={value.includes(option)} onChange={() => toggle(option)} />
      {option}
    </label>
  );
  return (
    <label className="image-prompt-multiselect">
      <span>{label}</span>
      <button
        type="button"
        className={value.length ? undefined : "is-empty"}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={(event) => {
          setAnchor(event.currentTarget);
          setOpen(!open);
        }}
      >
        <span>{value.length ? value.join("、") : "指定無し"}</span>
        <DropdownIndicator />
      </button>
      {open && anchor && (
        <PromptMenuPortal anchor={anchor} grouped={Boolean(groups)} onClose={() => setOpen(false)}>
          <div className={`image-prompt-multiselect-menu is-portaled${groups ? " is-grouped" : ""}`} role={groups ? "menu" : "listbox"} aria-multiselectable={groups ? undefined : "true"}>
            <button type="button" onClick={() => onChange([])}>
              <span>{value.length === 0 ? "✓" : ""}</span>選択を解除
            </button>
            {groups ? (
              <>
                {groups.map((group) => (
                  <button key={group.label} className="image-prompt-group-trigger" type="button" aria-haspopup="listbox" aria-expanded={activeGroup === group.label} onMouseEnter={() => setActiveGroup(group.label)} onFocus={() => setActiveGroup(group.label)} onClick={() => setActiveGroup(group.label)}>
                    {group.label}
                    <span aria-hidden="true">›</span>
                  </button>
                ))}
                {selectedGroup && (
                  <div className="image-prompt-multiselect-submenu" role="listbox" aria-multiselectable="true" aria-label={selectedGroup.label}>
                    {selectedGroup.options.map(optionCheckbox)}
                  </div>
                )}
              </>
            ) : (
              choices?.map(optionCheckbox)
            )}
          </div>
        </PromptMenuPortal>
      )}
    </label>
  );
}

function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const menus = useContext(PromptMenuContext);
  const open = menus?.active === label;
  const [anchor, setAnchor] = useState<HTMLDivElement | null>(null);
  const setOpen = (next: boolean) => menus?.setActive(next ? label : null);
  const selected = PROMPT_COLORS.find((option) => option.name === value);
  const color = /^#[0-9a-fA-F]{6}$/.test(value) ? value : (selected?.hex ?? "#000000");
  return (
    <label className="image-prompt-color-combobox">
      {label}
      <div>
        <input type="color" value={color} onChange={(event) => onChange(event.target.value.toUpperCase())} aria-label={`${label}をカラースウォッチで選択`} />
        <input
          value={value}
          onFocus={(event) => {
            setAnchor(event.currentTarget.parentElement as HTMLDivElement);
            setOpen(true);
          }}
          onChange={(event) => {
            setAnchor(event.currentTarget.parentElement as HTMLDivElement);
            onChange(event.target.value);
            setOpen(true);
          }}
          placeholder="指定無し"
        />
        <button
          type="button"
          aria-label={`${label}の候補を表示`}
          aria-expanded={open}
          onMouseDown={(event) => event.preventDefault()}
          onClick={(event) => {
            setAnchor(event.currentTarget.parentElement as HTMLDivElement);
            setOpen(!open);
          }}
        >
          <DropdownIndicator />
        </button>
        {open && anchor && (
          <PromptMenuPortal anchor={anchor} onClose={() => setOpen(false)}>
            <div className="image-prompt-combobox-menu image-prompt-color-menu is-portaled" role="listbox">
              {PROMPT_COLORS.map((option) => (
                <button
                  key={option.name}
                  type="button"
                  role="option"
                  aria-selected={value === option.name}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    onChange(option.name);
                    setOpen(false);
                  }}
                >
                  <i style={{ backgroundColor: option.hex }} aria-hidden="true" />
                  {option.name}
                </button>
              ))}
            </div>
          </PromptMenuPortal>
        )}
      </div>
    </label>
  );
}

export function CharacterImagePromptSuggestionDialog({ model: m }: { model: CharactersViewModel }) {
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  if (!m.imagePromptSuggestionOpen || !m.editing) return null;
  const appearance = prioritizedAppearanceOptions(m.editDetails.gender);
  return (
    <PromptMenuContext.Provider value={{ active: activeMenu, setActive: setActiveMenu }}>
      <div className="modal-backdrop">
        <form className="modal image-prompt-suggestion-modal" onSubmit={(event) => void m.suggestCharacterImagePrompt(event)}>
          <DialogHeader eyebrow="CAST IMAGE PROMPT" title="画像生成用プロンプト文を作る" description="選んだ外見を英語タグへ変換します。自由入力がある場合だけLLMで短いタグへ変換します。" />
          <div className="image-prompt-sections">
            <fieldset>
              <legend>基本</legend>
              <PromptCombobox label="画像上の主体" value={m.imagePromptSubject} choices={options.SUBJECT_OPTIONS} onChange={m.setImagePromptSubject} />
              <PromptCombobox label="年齢" value={m.imagePromptAgeImpression} choices={options.AGE_IMPRESSION_OPTIONS} onChange={m.setImagePromptAgeImpression} />
              <PromptCombobox label="体格" value={m.imagePromptBodyBuild} choices={options.BODY_BUILD_OPTIONS} onChange={m.setImagePromptBodyBuild} />
              <PromptCombobox label="身長" value={m.imagePromptHeight} choices={options.HEIGHT_OPTIONS} onChange={m.setImagePromptHeight} />
              <PromptCombobox label="バストサイズ" value={m.imagePromptBustSize} choices={options.BUST_SIZE_OPTIONS} onChange={m.setImagePromptBustSize} />
              <PromptCombobox label="肌の色" value={m.imagePromptSkinTone} choices={options.SKIN_TONE_OPTIONS} onChange={m.setImagePromptSkinTone} />
            </fieldset>
            <fieldset>
              <legend>顔・目・表情</legend>
              <PromptCombobox label="輪郭" value={m.imagePromptFaceContour} choices={options.FACE_CONTOUR_OPTIONS} onChange={m.setImagePromptFaceContour} />
              <PromptCombobox label="眉" value={m.imagePromptEyebrowShape} choices={options.EYEBROW_SHAPE_OPTIONS} onChange={m.setImagePromptEyebrowShape} />
              <ColorField label="目の色" value={m.imagePromptEyeColor} onChange={m.setImagePromptEyeColor} />
              <PromptCombobox label="目のスタイル" value={m.imagePromptEyeStyle} choices={options.EYE_STYLE_OPTIONS} onChange={m.setImagePromptEyeStyle} />
              <PromptMultiSelect label="ひげ" value={m.imagePromptFacialHair} groups={options.FACIAL_HAIR_GROUPS} onChange={m.setImagePromptFacialHair} />
              <PromptCombobox label="表情" value={m.imagePromptExpression} groups={EXPRESSION_GROUPS} onChange={m.setImagePromptExpression} />
              <PromptMultiSelect label="そばかす／ほくろ" value={m.imagePromptFrecklesMoles} groups={options.FRECKLES_MOLES_GROUPS} onChange={m.setImagePromptFrecklesMoles} />
              <PromptMultiSelect label="傷" value={m.imagePromptScars} groups={options.SCARS_GROUPS} onChange={m.setImagePromptScars} />
              <PromptMultiSelect label="タトゥー" value={m.imagePromptTattoos} groups={options.TATTOOS_GROUPS} onChange={m.setImagePromptTattoos} />
            </fieldset>
            <fieldset>
              <legend>髪</legend>
              <PromptCombobox label="長さ" value={m.imagePromptHairLength} choices={options.HAIR_LENGTH_OPTIONS} onChange={m.setImagePromptHairLength} />
              <PromptCombobox label="ヘアスタイル" value={m.imagePromptHairstyle} choices={appearance.hairstyles} onChange={m.setImagePromptHairstyle} />
              <PromptCombobox label="髪質" value={m.imagePromptHairTexture} choices={options.HAIR_TEXTURE_OPTIONS} onChange={m.setImagePromptHairTexture} />
              <PromptCombobox label="前髪" value={m.imagePromptBangs} choices={options.BANGS_OPTIONS} onChange={m.setImagePromptBangs} />
              <ColorField label="髪色" value={m.imagePromptHairColor} onChange={m.setImagePromptHairColor} />
              <label className="image-prompt-secondary-hair-toggle">
                <input type="checkbox" checked={m.imagePromptSecondaryHairColorEnabled} onChange={(event) => m.setImagePromptSecondaryHairColorEnabled(event.target.checked)} />
                髪色2を使う
              </label>
              {m.imagePromptSecondaryHairColorEnabled && (
                <>
                  <ColorField label="髪色2" value={m.imagePromptSecondaryHairColor} onChange={m.setImagePromptSecondaryHairColor} />
                  <PromptCombobox label="配色方式" value={m.imagePromptSecondaryHairColorStyle} choices={options.SECONDARY_HAIR_COLOR_STYLE_OPTIONS} onChange={m.setImagePromptSecondaryHairColorStyle} />
                </>
              )}
            </fieldset>
            <fieldset>
              <legend>服装</legend>
              <PromptCombobox label="職業" value={m.imagePromptOccupation} groups={OCCUPATION_GROUPS} onChange={m.setImagePromptOccupation} />
              <PromptCombobox label="服装" value={m.imagePromptOutfit} choices={appearance.outfits} onChange={m.setImagePromptOutfit} />
              <PromptCombobox label="服装の印象" value={m.imagePromptOutfitImpression} choices={options.OUTFIT_IMPRESSION_OPTIONS} onChange={m.setImagePromptOutfitImpression} />
              <PromptMultiSelect label="アクセサリー" value={m.imagePromptAccessory} groups={ACCESSORY_GROUPS} onChange={m.setImagePromptAccessory} />
            </fieldset>
            <fieldset>
              <legend>ポーズ</legend>
              <PromptCombobox label="全身動作" value={m.imagePromptPose} choices={options.POSE_OPTIONS} onChange={m.setImagePromptPose} />
              <PromptCombobox label="手・腕ジェスチャー" value={m.imagePromptGestures[0] ?? ""} choices={options.GESTURE_OPTIONS} onChange={(value) => m.setImagePromptGestures(value ? [value] : [])} />
            </fieldset>
            <fieldset>
              <legend>画面構成</legend>
              <PromptCombobox label="画風" value={m.imagePromptStyle} choices={options.STYLE_OPTIONS} onChange={m.setImagePromptStyle} />
              <PromptCombobox label="構図" value={m.imagePromptComposition} groups={options.COMPOSITION_GROUPS} descriptions={options.COMPOSITION_DESCRIPTIONS} onChange={m.setImagePromptComposition} />
              <PromptCombobox label="カメラアングル" value={m.imagePromptCameraAngle} groups={options.CAMERA_ANGLE_GROUPS} descriptions={options.CAMERA_ANGLE_DESCRIPTIONS} onChange={m.setImagePromptCameraAngle} />
              <PromptCombobox label="画面効果・技法" value={m.imagePromptScreenEffect} groups={options.SCREEN_EFFECT_GROUPS} descriptions={options.SCREEN_EFFECT_DESCRIPTIONS} onChange={m.setImagePromptScreenEffect} />
            </fieldset>
            <fieldset>
              <legend>背景</legend>
              <PromptCombobox label="背景の種類" value={m.imagePromptBackground} choices={options.BACKGROUND_OPTIONS} onChange={m.setImagePromptBackground} />
              {m.imagePromptBackground === "単色" && <ColorField label="背景色" value={m.imagePromptBackgroundDetails.color} onChange={(color) => m.setImagePromptBackgroundDetails((current) => ({ ...current, color }))} />}
              {m.imagePromptBackground === "グラデーション" && (
                <>
                  <ColorField label="グラデーション色1" value={m.imagePromptBackgroundDetails.gradientColor1} onChange={(gradientColor1) => m.setImagePromptBackgroundDetails((current) => ({ ...current, gradientColor1 }))} />
                  <ColorField label="グラデーション色2" value={m.imagePromptBackgroundDetails.gradientColor2} onChange={(gradientColor2) => m.setImagePromptBackgroundDetails((current) => ({ ...current, gradientColor2 }))} />
                  <PromptCombobox label="グラデーション方向" value={m.imagePromptBackgroundDetails.gradientDirection} choices={options.GRADIENT_DIRECTION_OPTIONS} onChange={(gradientDirection) => m.setImagePromptBackgroundDetails((current) => ({ ...current, gradientDirection }))} />
                </>
              )}
            </fieldset>
            <fieldset className="image-prompt-request-section">
              <legend>追加の要望</legend>
              <label className="image-prompt-request">
                追加の要望（任意）
                <textarea
                  value={m.imagePromptRequest}
                  onChange={(event) => {
                    m.setImagePromptRequest(event.target.value);
                    m.setImagePromptSuggestionError("");
                  }}
                  placeholder="特徴、衣装、表情、背景の内容など。"
                />
              </label>
            </fieldset>
          </div>
          {m.imagePromptSuggestionError && (
            <p className="character-profile-suggestion-error" role="alert">
              {m.imagePromptSuggestionError}
            </p>
          )}
          <DialogFooter className="image-prompt-footer">
            <button type="button" disabled={m.suggestingImagePrompt} onClick={() => m.setImagePromptSuggestionOpen(false)}>
              キャンセル
            </button>
            <button className="primary" disabled={m.suggestingImagePrompt}>
              {m.suggestingImagePrompt ? "プロンプトを作成中…" : "プロンプトを作成"}
            </button>
          </DialogFooter>
        </form>
      </div>
    </PromptMenuContext.Provider>
  );
}
