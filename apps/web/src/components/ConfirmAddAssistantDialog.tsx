import Modal from "./ui/Modal";
import Button from "./ui/Button";

interface Props {
  email: string;
  busy: boolean;
  onEdit: () => void;
  onConfirm: () => void;
}

/**
 * The server answers "created", "linked" and "already on your team" the same
 * way, and must not be asked "who is this?" first - that answer would be an
 * account oracle ([0.21.0] ENUMERATION). So the only thing worth confirming is
 * what the instructor typed: a typo here invites a stranger.
 */
export default function ConfirmAddAssistantDialog({
  email,
  busy,
  onEdit,
  onConfirm,
}: Props) {
  return (
    <Modal
      title="Add this teaching assistant?"
      onClose={onEdit}
      busy={busy}
      footer={
        <>
          <Button variant="secondary" onClick={onEdit} disabled={busy}>
            Edit email
          </Button>
          <Button onClick={onConfirm} disabled={busy}>
            {busy ? "Adding…" : "Add to my team"}
          </Button>
        </>
      }
    >
      <div className="rounded-lg border border-border bg-modal-muted px-4 py-3.5">
        <p className="font-mono text-sm break-all text-foreground">{email}</p>
      </div>
      <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
        If this address doesn't have an account yet, we'll email an invite to
        it. Check it's spelled right.
      </p>
    </Modal>
  );
}
