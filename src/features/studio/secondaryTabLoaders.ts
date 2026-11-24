export const loadCharactersView = () => import("../characters/CharactersView").then((module) => ({ default: module.CharactersView }));
export const loadDraftView = () => import("../draft/DraftView").then((module) => ({ default: module.DraftView }));
export const loadSettingsView = () => import("../settings/SettingsView").then((module) => ({ default: module.SettingsView }));
