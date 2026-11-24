const sections = [
  ["foundations", "基礎"],
  ["surfaces", "共通面"],
  ["controls", "操作"],
  ["custom-buttons", "固有ボタン"],
  ["insert-controls", "挿入"],
  ["forms", "フォーム"],
  ["models", "モデル"],
  ["dialogs", "ダイアログ"],
  ["feedback", "状態"],
  ["audit", "CSS監査"],
] as const;

export function StyleGuideIndex() {
  return (
    <nav className="styleguide-index" aria-label="コンポーネント一覧">
      {sections.map(([id, label]) => (
        <a href={`#${id}`} key={id}>
          {label}
        </a>
      ))}
    </nav>
  );
}
