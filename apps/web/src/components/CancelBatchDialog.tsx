import Modal from "./ui/Modal";
import Button from "./ui/Button";

interface CancelBatchDialogProps {
  open: boolean;
  fileName: string | null;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export default function CancelBatchDialog({
  open,
  fileName,
  busy,
  onClose,
  onConfirm,
}: CancelBatchDialogProps) {
  if (!open) return null;

  return (
    <Modal
      title="Stop this batch?"
      subtitle={fileName ?? undefined}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Keep screening
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={busy}>
            {busy ? "Stopping…" : "Stop batch"}
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted-foreground">
        Rows already scored stay saved. Rows still waiting will be skipped
        instead of checked — there is no undo, but you can re-upload the
        remaining rows in a new batch at any time.
      </p>
    </Modal>
  );
}
