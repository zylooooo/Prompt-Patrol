import { useState } from "react";
import Modal from "./ui/Modal";
import Button from "./ui/Button";
import { displayName, type AppUser } from "../types";

const REASON_MAX_LENGTH = 500;

/**
 * Mirrors the server's normalisation (users schema `_clean_reason`) so what the
 * person sees is what is stored. The server remains the authority; this only
 * avoids sending markup or control characters in the first place.
 */
function cleanReason(raw: string): string | undefined {
  const cleaned = Array.from(raw)
    .filter((ch) => {
      const c = ch.charCodeAt(0);
      const control =
        (c < 0x20 && c !== 0x09 && c !== 0x0a) || (c >= 0x7f && c <= 0x9f);
      return !control && ch !== "<" && ch !== ">";
    })
    .join("");
  return cleaned.trim() || undefined;
}

interface DeactivateReasonDialogProps {
  user: AppUser;
  busy?: boolean;
  onClose: () => void;
  onConfirm: (reason: string | undefined) => void;
}

/**
 * Optional note recorded on the audit trail when access is paused. Plain text
 * only: it is rendered by React as text and never as HTML anywhere.
 */
export default function DeactivateReasonDialog({
  user,
  busy,
  onClose,
  onConfirm,
}: DeactivateReasonDialogProps) {
  const [reason, setReason] = useState("");

  return (
    <Modal
      title={`Deactivate ${displayName(user)}?`}
      busy={busy}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => onConfirm(cleanReason(reason))}
            disabled={busy}
          >
            {busy ? "Deactivating…" : "Deactivate account"}
          </Button>
        </>
      }
    >
      <p className="text-sm leading-relaxed text-muted-foreground">
        They will be signed out and unable to sign in until reactivated. Their
        past records stay intact.
      </p>
      <label className="mt-4 flex flex-col gap-2">
        <span className="text-xs text-muted-foreground">
          Reason (optional, kept in the audit log and not shown to them)
        </span>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={REASON_MAX_LENGTH}
          rows={3}
          disabled={busy}
          className="resize-none rounded-md border border-input-border bg-input-bg px-3.5 py-2.5 text-sm text-foreground placeholder:text-input-placeholder transition focus-visible:bg-accent-soft"
        />
        <span className="self-end text-xs text-disabled-foreground">
          {reason.length}/{REASON_MAX_LENGTH}
        </span>
      </label>
    </Modal>
  );
}
