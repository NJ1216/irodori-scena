export type DictionaryScope = "global" | "project";
export const dictionaryScopes = ["global", "project"] as const;
export const termKey = (value: string) => value.trim().toLocaleLowerCase();
