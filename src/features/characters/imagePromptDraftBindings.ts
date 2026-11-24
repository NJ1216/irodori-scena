import type { Dispatch, SetStateAction } from "react";
import type { ImagePromptDraft } from "./imagePromptDraft";

type Update = <K extends keyof ImagePromptDraft>(field: K, value: ImagePromptDraft[K]) => void;
type BackgroundDetails = { color: string; gradientColor1: string; gradientColor2: string; gradientDirection: string };

function bindBackgroundDetails(d: ImagePromptDraft, update: Update) {
  const backgroundDetails: BackgroundDetails = { color: d.background_color, gradientColor1: d.background_gradient_color1, gradientColor2: d.background_gradient_color2, gradientDirection: d.background_gradient_direction };
  const setBackgroundDetails: Dispatch<SetStateAction<BackgroundDetails>> = (next) => {
    const value = typeof next === "function" ? next(backgroundDetails) : next;
    update("background_color", value.color);
    update("background_gradient_color1", value.gradientColor1);
    update("background_gradient_color2", value.gradientColor2);
    update("background_gradient_direction", value.gradientDirection);
  };
  return { backgroundDetails, setBackgroundDetails };
}

export function imagePromptDraftBindings(d: ImagePromptDraft, update: Update) {
  const { backgroundDetails, setBackgroundDetails } = bindBackgroundDetails(d, update);
  const bind = <K extends keyof ImagePromptDraft>(key: K) => [(d[key] ?? "") as ImagePromptDraft[K], (value: ImagePromptDraft[K]) => update(key, value)] as const;
  const [imagePromptSubject, setImagePromptSubject] = bind("subject");
  const [imagePromptHairColor, setImagePromptHairColor] = bind("hair_color");
  const [imagePromptSecondaryHairColorEnabled, setImagePromptSecondaryHairColorEnabled] = bind("secondary_hair_color_enabled");
  const [imagePromptSecondaryHairColor, setImagePromptSecondaryHairColor] = bind("secondary_hair_color");
  const [imagePromptSecondaryHairColorStyle, setImagePromptSecondaryHairColorStyle] = bind("secondary_hair_color_style");
  const [imagePromptEyeColor, setImagePromptEyeColor] = bind("eye_color");
  const [imagePromptEyeStyle, setImagePromptEyeStyle] = bind("eye_style");
  const [imagePromptHairLength, setImagePromptHairLength] = bind("hair_length");
  const [imagePromptHairstyle, setImagePromptHairstyle] = bind("hairstyle");
  const [imagePromptExpression, setImagePromptExpression] = bind("expression");
  const [imagePromptOutfit, setImagePromptOutfit] = bind("outfit");
  const [imagePromptOutfitImpression, setImagePromptOutfitImpression] = bind("outfit_impression");
  const [imagePromptOccupation, setImagePromptOccupation] = bind("occupation");
  const [imagePromptAccessory, setImagePromptAccessory] = bind("accessory");
  const [imagePromptStyle, setImagePromptStyle] = bind("style");
  const [imagePromptComposition, setImagePromptComposition] = bind("composition");
  const [imagePromptScreenEffect, setImagePromptScreenEffect] = bind("screen_effect");
  const [imagePromptBackground, setImagePromptBackground] = bind("background");
  const [imagePromptPose, setImagePromptPose] = bind("pose");
  const [imagePromptGestures, setImagePromptGestures] = bind("gestures");
  const [imagePromptCameraAngle, setImagePromptCameraAngle] = bind("camera_angle");
  const [imagePromptSkinTone, setImagePromptSkinTone] = bind("skin_tone");
  const [imagePromptHairTexture, setImagePromptHairTexture] = bind("hair_texture");
  const [imagePromptBangs, setImagePromptBangs] = bind("bangs");
  const [imagePromptFacialHair, setImagePromptFacialHair] = bind("facial_hair");
  const [imagePromptBodyBuild, setImagePromptBodyBuild] = bind("body_build");
  const [imagePromptAgeImpression, setImagePromptAgeImpression] = bind("age_impression");
  const [imagePromptFaceContour, setImagePromptFaceContour] = bind("face_contour");
  const [imagePromptEyebrowShape, setImagePromptEyebrowShape] = bind("eyebrow_shape");
  const [imagePromptMakeup, setImagePromptMakeup] = bind("makeup");
  const [imagePromptHeight, setImagePromptHeight] = bind("height");
  const [imagePromptBustSize, setImagePromptBustSize] = bind("bust_size");
  const [imagePromptFrecklesMoles, setImagePromptFrecklesMoles] = bind("freckles_moles");
  const [imagePromptScars, setImagePromptScars] = bind("scars");
  const [imagePromptTattoos, setImagePromptTattoos] = bind("tattoos");
  const [imagePromptRequest, setImagePromptRequest] = bind("request");
  return {
    imagePromptSubject,
    setImagePromptSubject,
    imagePromptHairColor,
    setImagePromptHairColor,
    imagePromptSecondaryHairColorEnabled,
    setImagePromptSecondaryHairColorEnabled,
    imagePromptSecondaryHairColor,
    setImagePromptSecondaryHairColor,
    imagePromptSecondaryHairColorStyle,
    setImagePromptSecondaryHairColorStyle,
    imagePromptEyeColor,
    setImagePromptEyeColor,
    imagePromptEyeStyle,
    setImagePromptEyeStyle,
    imagePromptHairLength,
    setImagePromptHairLength,
    imagePromptHairstyle,
    setImagePromptHairstyle,
    imagePromptExpression,
    setImagePromptExpression,
    imagePromptOutfit,
    setImagePromptOutfit,
    imagePromptOutfitImpression,
    setImagePromptOutfitImpression,
    imagePromptOccupation,
    setImagePromptOccupation,
    imagePromptAccessory,
    setImagePromptAccessory,
    imagePromptStyle,
    setImagePromptStyle,
    imagePromptComposition,
    setImagePromptComposition,
    imagePromptScreenEffect,
    setImagePromptScreenEffect,
    imagePromptBackground,
    setImagePromptBackground,
    imagePromptBackgroundDetails: backgroundDetails,
    setImagePromptBackgroundDetails: setBackgroundDetails,
    imagePromptPose,
    setImagePromptPose,
    imagePromptGestures,
    setImagePromptGestures,
    imagePromptCameraAngle,
    setImagePromptCameraAngle,
    imagePromptSkinTone,
    setImagePromptSkinTone,
    imagePromptHairTexture,
    setImagePromptHairTexture,
    imagePromptBangs,
    setImagePromptBangs,
    imagePromptFacialHair,
    setImagePromptFacialHair,
    imagePromptBodyBuild,
    setImagePromptBodyBuild,
    imagePromptAgeImpression,
    setImagePromptAgeImpression,
    imagePromptFaceContour,
    setImagePromptFaceContour,
    imagePromptEyebrowShape,
    setImagePromptEyebrowShape,
    imagePromptMakeup,
    setImagePromptMakeup,
    imagePromptHeight,
    setImagePromptHeight,
    imagePromptBustSize,
    setImagePromptBustSize,
    imagePromptFrecklesMoles,
    setImagePromptFrecklesMoles,
    imagePromptScars,
    setImagePromptScars,
    imagePromptTattoos,
    setImagePromptTattoos,
    imagePromptRequest,
    setImagePromptRequest,
  };
}
