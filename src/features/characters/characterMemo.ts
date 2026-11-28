export const CHARACTER_MEMO_MAX_LENGTH = 2000;

export function characterMemoLength(value: string) {
  return Array.from(value).length;
}

export function characterMemoLimitError(value: string) {
  const length = characterMemoLength(value);
  return length > CHARACTER_MEMO_MAX_LENGTH ? `自由メモは2,000文字以内で入力してください。現在${length.toLocaleString("ja-JP")}文字です。` : "";
}

/** Reports the memo limit inline; the memo field already shows the message, so this only marks and focuses it. */
export function reportCharacterMemoLimit(value: string, report: (message: string, field?: string) => void, field: string) {
  const error = characterMemoLimitError(value);
  if (error) report(error, field);
  return Boolean(error);
}
