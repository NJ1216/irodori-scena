export function StepHeading({ number, children }: { number: number; children: string }) {
  return (
    <h2 className="type-section-title draft-step-heading">
      <span aria-hidden="true">
        <span className="circle-number-glyph">{number}</span>
      </span>
      {children}
    </h2>
  );
}
