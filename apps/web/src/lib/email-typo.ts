const COMMON_DOMAINS = [
  "gmail.com",
  "outlook.com",
  "hotmail.com",
  "yahoo.com",
  "icloud.com",
  "smu.edu.sg",
];

// Real domains that sit within edit distance 2 of a common one; never "correct" them.
const KNOWN_OK_DOMAINS = [
  "ntu.edu.sg",
  "sit.edu.sg",
  "sutd.edu.sg",
  "nus.edu.sg",
  "u.nus.edu",
  "suss.edu.sg",
];

// Edit distance, capped: we only care whether it is 1 or 2.
function distance(a: string, b: string): number {
  const row = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0];
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const tmp = row[j];
      row[j] = Math.min(
        row[j] + 1,
        row[j - 1] + 1,
        prev + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
      prev = tmp;
    }
  }
  return row[b.length];
}

/** The corrected address when the domain is a near miss of a common one, else null. Never blocks; only suggests. */
export function suggestEmailDomain(email: string): string | null {
  const at = email.lastIndexOf("@");
  if (at < 1 || at === email.length - 1) return null;
  const local = email.slice(0, at);
  const domain = email.slice(at + 1).toLowerCase();
  if (COMMON_DOMAINS.includes(domain) || KNOWN_OK_DOMAINS.includes(domain))
    return null;
  const match = COMMON_DOMAINS.find((known) => distance(domain, known) <= 2);
  return match ? `${local}@${match}` : null;
}
