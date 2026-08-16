import Modal from "./ui/Modal";
import Button from "./ui/Button";
import { displayName, type AppUser } from "../types";

interface ConfirmDeleteDialogProps {
  user: AppUser | null;
  onClose: () => void;
  onConfirm: (user: AppUser) => void;
}

export default function ConfirmDeleteDialog({
  user,
  onClose,
  onConfirm,
}: ConfirmDeleteDialogProps) {
  if (!user) return null;

  return (
    <Modal
      title={`Delete ${displayName(user)}?`}
      subtitle="This cannot be undone."
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={() => onConfirm(user)}>
            Delete account
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm text-muted-foreground">
        <p>
          <span className="font-medium text-foreground">
            {displayName(user)}
          </span>{" "}
          will be removed from the accounts list and will not be able to sign
          in. There is no undo — restoring is not possible.
        </p>
        <p>
          Their past records stay intact, and their email address is released,
          so they can be provisioned again later as a new account if they ever
          return.
        </p>
        <p>
          If you only need to remove access for now, close this and choose{" "}
          <span className="font-medium text-foreground">Deactivate</span>{" "}
          instead — that can be reversed.
        </p>
      </div>
    </Modal>
  );
}
