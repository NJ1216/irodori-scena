import { shortcutLabel } from "../shared/platform";

const groups = [
  {
    title: "選択・編集",
    items: [
      [".数字. / Enter", "発話行番号へジャンプ"],
      [".シーン記号. / Enter", "シーン先頭へジャンプ"],
      ["↑ / ↓", "発話行を移動"],
      ["⌘F", "検索・置換"],
      ["⌘R", "選択した本文にルビを設定"],
      ["Enter / ⇧Enter", "検索中の次／前"],
      ["Escape", "検索を閉じる"],
      ["⌘Enter", "カーソル位置で発話行を分割"],
      ["F3", "表情パレットを表示／非表示"],
      ["⇧↑ / ⇧↓", "範囲を選択"],
      ["⌘A", "全発話行を選択"],
      ["Delete", "選択行を削除"],
    ],
  },
  {
    title: "生成",
    items: [
      ["⌘⌥R", "選択行へ新規テイク"],
      ["⌘⇧R", "選択行のテイクを置換"],
    ],
  },
  {
    title: "再生・プロジェクト",
    items: [
      ["Space", "連続再生／停止"],
      ["F", "連続再生のFollow／解除"],
      ["R", "自動生成 ON Follow → ON UnFollow → OFF"],
      ["⌘P", "選択行を台本順に再生／停止"],
      ["⌘⇧P", "選択行を上書き生成して再生"],
      ["⌘⌥P", "選択行を追加生成して再生"],
      ["⌘N", "新規プロジェクト"],
      ["⌘O / ⌘S", "開く／初回保存"],
    ],
  },
];

export function ShortcutReference() {
  return (
    <section className="shortcut-card" aria-label="ショートカット">
      <h3>ショートカット</h3>
      {groups.map((group) => (
        <div className="shortcut-group" key={group.title}>
          <h4>{group.title}</h4>
          {group.items.map(([keys, action]) => (
            <div className="shortcut-row" key={keys}>
              <kbd>{shortcutLabel(keys)}</kbd>
              <span>{action}</span>
            </div>
          ))}
        </div>
      ))}
      <p>R系だけが選択範囲へ適用されます。入力中・ダイアログ表示中・競合する処理中は操作できません。</p>
    </section>
  );
}
