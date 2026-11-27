/** Byte sizes are shown in decimal units everywhere: 1 GB = 1,000,000,000 bytes. */
const GB = 1_000_000_000;
const MB = 1_000_000;

export function formatGb(bytes: number, digits = 1): string {
  return `${(bytes / GB).toFixed(digits)} GB`;
}

/** MB below one gigabyte (at least 1 MB), GB above. */
export function formatDecimalBytes(bytes: number): string {
  const megabytes = Math.max(1, Math.round(bytes / MB));
  return megabytes < 1000 ? `${megabytes} MB` : formatGb(bytes);
}
