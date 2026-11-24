import { useMemo, useState } from "react";
import metadata from "../../../release-metadata.json";
import { openExternal } from "../../api";
import { licenseScopeLabel, type LicenseEntry, type Notices } from "./licenseNotices";

const PAGE_SIZE = 30;

function LicenseDocument({ entry, notices }: { entry: LicenseEntry | null; notices: Notices }) {
  return (
    <article className="license-document" aria-label="選択したライセンス">
      <header className="license-document-heading">
        <p className="eyebrow">{entry ? licenseScopeLabel(entry.scope) : "アプリケーション"}</p>
        <h3>{entry?.name ?? "irodori SCENA"}</h3>
        <p className="subtle">
          {entry?.version ?? `v${metadata.version.replace("-beta", " beta")}`} · {entry?.license ?? `${metadata.license} License`}
        </p>
        {entry?.status !== undefined && entry.status !== "collected" && <p className="subtle">権利情報の確認中</p>}
        <button type="button" className="quiet-button" onClick={() => void openExternal(entry?.source ?? metadata.repository)}>
          {entry ? "配布元を開く" : "GitHub・お問い合わせ"}
        </button>
      </header>
      <div className="license-document-body" tabIndex={0} aria-label="ライセンス本文">
        {entry ? entry.texts.map((text) => <pre key={`${text.name}-${text.sha256}`}>{notices.texts[text.sha256]}</pre>) : <pre>{notices.applicationLicense}</pre>}
      </div>
    </article>
  );
}

export function LicenseBrowser({ notices }: { notices: Notices }) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<LicenseEntry | null>(null);
  const entries = useMemo(() => notices.entries.filter((entry) => `${entry.name} ${entry.license} ${licenseScopeLabel(entry.scope)}`.toLowerCase().includes(query.toLowerCase())), [notices, query]);
  const pages = Math.max(1, Math.ceil(entries.length / PAGE_SIZE));
  return (
    <div className="license-workspace">
      <aside className="license-sidebar" aria-label="ライセンス一覧">
        <label className="license-search">
          ライブラリを検索
          <input
            type="search"
            value={query}
            placeholder="名前・ライセンス"
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(0);
            }}
          />
        </label>
        <button type="button" className="quiet-button license-choice" aria-pressed={selected === null} onClick={() => setSelected(null)}>
          <strong>irodori SCENA</strong>
          <small>本体 · MIT License</small>
        </button>
        <p className="license-count subtle" role="status">
          使用ライブラリ · {entries.length} 件
        </p>
        <nav className="license-results" aria-label="使用ライブラリ" key={`${query}-${page}`}>
          {entries.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map((entry) => (
            <button type="button" className="quiet-button license-choice" aria-label={`${entry.name} ${entry.version}`} key={entry.id} aria-pressed={selected?.id === entry.id} onClick={() => setSelected(entry)}>
              <strong>{entry.name}</strong>
              <small>{entry.version}</small>
            </button>
          ))}
          {!entries.length && <p className="subtle license-empty">該当するライブラリはありません。</p>}
        </nav>
        <div className="license-pagination" aria-label="ライブラリ一覧のページ">
          <button type="button" className="quiet-button" disabled={page === 0} onClick={() => setPage(page - 1)} aria-label="前のページ">
            ‹
          </button>
          <span className="subtle">
            {page + 1} / {pages}
          </span>
          <button type="button" className="quiet-button" disabled={page + 1 === pages} onClick={() => setPage(page + 1)} aria-label="次のページ">
            ›
          </button>
        </div>
      </aside>
      <LicenseDocument key={selected?.id ?? "application"} entry={selected} notices={notices} />
    </div>
  );
}
