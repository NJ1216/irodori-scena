import type { ReactNode } from "react";

export function Section({ id, title, source, children }: { id: string; title: string; source: string; children: ReactNode }) {
  return (
    <section className="styleguide-section" id={id}>
      <header>
        <div>
          <p className="eyebrow">{source}</p>
          <h2>{title}</h2>
        </div>
        <span className="styleguide-source">src/styles/{source}</span>
      </header>
      {children}
    </section>
  );
}

export function Card({ children }: { children: ReactNode }) {
  return <article className="styleguide-card">{children}</article>;
}
