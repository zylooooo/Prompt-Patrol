import { useState } from "react";
import { suggestEmailDomain } from "../lib/email-typo";

/** Submit guard for an email field: one "Did you mean…?" pause per address, never a block. */
export function useEmailTypoGuard(
  email: string,
  setEmail: (next: string) => void,
) {
  const [found, setFound] = useState<string | null>(null);
  const [kept, setKept] = useState<string | null>(null);
  const [seen, setSeen] = useState(email);
  // Any edit clears both the hint and an earlier "keep as typed" (adjusting
  // state during render, not in an effect). Restoring an earlier value does
  // not resurrect either.
  if (seen !== email) {
    setSeen(email);
    setFound(null);
    setKept(null);
  }
  const suggestion = kept === email ? null : found;

  function check(): boolean {
    if (kept === email) return true;
    const next = suggestEmailDomain(email.trim());
    if (next === null) return true;
    setFound(next);
    return false;
  }

  return {
    suggestion,
    check,
    applySuggestion: () => {
      if (suggestion) setEmail(suggestion);
    },
    keepAsTyped: () => {
      setKept(email);
    },
  };
}
