import type { ImagePromptPreferences } from "../../types";

type MultiSelectField = "accessory" | "facial_hair" | "freckles_moles" | "scars" | "tattoos";
export type ImagePromptDraft = Omit<Required<Omit<ImagePromptPreferences, "output_language">>, MultiSelectField> & Record<MultiSelectField, string[]>;

const multiValue = (value: string | string[] | undefined) => (Array.isArray(value) ? value : (value ?? "").split(",")).map((item) => item.trim()).filter(Boolean);

export function emptyImagePromptDraft(): ImagePromptDraft {
  return {
    subject: "",
    hair_color: "",
    secondary_hair_color_enabled: false,
    secondary_hair_color: "",
    secondary_hair_color_style: "",
    eye_color: "",
    eye_style: "",
    hair_length: "",
    hairstyle: "",
    expression: "",
    outfit: "",
    outfit_impression: "",
    occupation: "",
    accessory: [],
    style: "",
    composition: "",
    screen_effect: "",
    pose: "",
    gestures: [],
    camera_angle: "",
    background_color: "",
    background_gradient_color1: "",
    background_gradient_color2: "",
    background_gradient_direction: "",
    background: "",
    skin_tone: "",
    hair_texture: "",
    bangs: "",
    facial_hair: [],
    body_build: "",
    age_impression: "",
    face_contour: "",
    eyebrow_shape: "",
    makeup: "",
    height: "",
    bust_size: "",
    freckles_moles: [],
    scars: [],
    tattoos: [],
    request: "",
  };
}

export function imagePromptDraftFromPreferences(preferences?: ImagePromptPreferences): ImagePromptDraft {
  if (!preferences) return emptyImagePromptDraft();
  return {
    ...emptyImagePromptDraft(),
    ...preferences,
    makeup: "",
    accessory: multiValue(preferences.accessory),
    facial_hair: multiValue(preferences.facial_hair),
    freckles_moles: multiValue(preferences.freckles_moles),
    scars: multiValue(preferences.scars),
    tattoos: multiValue(preferences.tattoos),
    gestures: preferences.gestures?.slice(0, 1) ?? [],
  };
}

export function imagePromptPreferencesFromDraft(draft: ImagePromptDraft) {
  return {
    ...draft,
    output_language: "english" as const,
    makeup: "",
    accessory: draft.accessory.join(", "),
    facial_hair: draft.facial_hair.join(", "),
    freckles_moles: draft.freckles_moles.join(", "),
    scars: draft.scars.join(", "),
    tattoos: draft.tattoos.join(", "),
    gestures: draft.gestures.slice(0, 1),
  };
}

export const imagePromptRequestFromDraft = imagePromptPreferencesFromDraft;
