// Mirrors the server rule (DECISION LOG [0.31.0]) so the form can explain it
// before sending. The server still decides.
const SMU_DOMAIN = "smu.edu.sg";

export const SMU_ONLY_MESSAGE =
  "Only SMU email addresses can be added. Use one ending in smu.edu.sg, such as name@smu.edu.sg or name@scis.smu.edu.sg.";

export const INCOMPLETE_EMAIL_MESSAGE =
  "Enter a full email address, such as name@smu.edu.sg.";

/** Why this address can't be added, or null when it can. */
export function emailProblem(email: string): string | null {
  const at = email.lastIndexOf("@");
  if (at < 1 || at === email.length - 1) return INCOMPLETE_EMAIL_MESSAGE;
  return isSmuEmail(email) ? null : SMU_ONLY_MESSAGE;
}

/** True for smu.edu.sg and any subdomain of it. */
export function isSmuEmail(email: string): boolean {
  const at = email.lastIndexOf("@");
  if (at < 1) return false;
  const domain = email.slice(at + 1).toLowerCase();
  return domain === SMU_DOMAIN || domain.endsWith(`.${SMU_DOMAIN}`);
}
