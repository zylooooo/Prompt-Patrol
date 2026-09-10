const KEY = "pp_active_batch";

export interface ActiveBatch {
  email: string;
  batchId: string;
  fileName: string;
  rowTotal: number;
}

export function readActiveBatch(email: string): ActiveBatch | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ActiveBatch;
    return parsed.email === email ? parsed : null;
  } catch {
    return null;
  }
}

export function writeActiveBatch(batch: ActiveBatch): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(batch));
  } catch {
    // storage unavailable (private mode, quota) - resuming across reloads
    // just won't work, the current session still does
  }
}

export function clearActiveBatch(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
