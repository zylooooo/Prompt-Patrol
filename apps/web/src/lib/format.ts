export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  const date = d.toLocaleDateString("en-SG", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  const time = d.toLocaleTimeString("en-SG", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return `${date}, ${time}`;
}

export function fmtDateOnly(iso: string): string {
  return new Date(iso).toLocaleDateString("en-SG", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function fmtDateShort(iso: string): string {
  const d = new Date(iso);
  const date = d.toLocaleDateString("en-SG", {
    day: "numeric",
    month: "short",
  });
  const time = d.toLocaleTimeString("en-SG", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return `${date}, ${time}`;
}

export function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

export function truncate(text: string, max = 70): string {
  return text.length > max ? `${text.slice(0, max).trimEnd()}…` : text;
}
