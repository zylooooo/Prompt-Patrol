const ZERO_MIN = /^(0|0px|0rem|0em|0fr|0%)$/i;
const DEFAULT_COLUMN_MIN = "8rem";

export function resolveGridColumnWidth(width: string): string {
  const trimmed = width.trim();
  const minmax = trimmed.match(/^minmax\(\s*([^,]+)\s*,\s*(.+)\s*\)$/i);
  if (minmax) {
    const min = minmax[1].trim();
    const max = minmax[2].trim();
    if (ZERO_MIN.test(min)) {
      return `minmax(${DEFAULT_COLUMN_MIN}, ${max})`;
    }
    return trimmed;
  }
  if (/^\d+(\.\d+)?fr$/i.test(trimmed)) {
    return `minmax(${DEFAULT_COLUMN_MIN}, ${trimmed})`;
  }
  return trimmed;
}
