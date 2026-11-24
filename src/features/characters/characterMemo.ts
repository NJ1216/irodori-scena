export const CHARACTER_MEMO_MAX_LENGTH = 2000;

export function characterMemoLength(value: string) {
  return Array.from(value).length;
}

export function characterMemoLimitError(value: string) {
  const length = characterMemoLength(value);
  return length > CHARACTER_MEMO_MAX_LENGTH ? `自由メモは2,000文字以内で入力してください。現在${length.toLocaleString("ja-JP")}文字です。` : "";
}

export function notifyCharacterMemoLimit(value: string, notify: (message: string) => void) {
  const error = characterMemoLimitError(value);
  if (error) notify(error);
  return Boolean(error);
}
