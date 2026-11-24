export function revealVoiceSampleEmojis(details: HTMLDetailsElement) {
  if (!details.open) return;
  requestAnimationFrame(() => {
    if (!details.isConnected || !details.open) return;
    const palette = details.querySelector<HTMLElement>(".emoji-palette");
    const dialog = details.closest<HTMLElement>(".modal");
    const footer = dialog?.querySelector<HTMLElement>(".dialog-footer");
    if (!palette || !dialog || !footer) return;
    const bounds = palette.getBoundingClientRect();
    if (bounds.bottom > footer.getBoundingClientRect().top || bounds.top < dialog.getBoundingClientRect().top) {
      palette.scrollIntoView({ block: "center" });
    }
  });
}
