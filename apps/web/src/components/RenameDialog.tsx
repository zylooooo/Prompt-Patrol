import { useState } from "react";
import Modal from "./ui/Modal";
import Button from "./ui/Button";
import { useToast } from "../hooks/useToast";
import { useUpdateDisplayName } from "../hooks/useUsers";

const FIELD =
  "h-11 w-full rounded-md border border-input-border bg-input-bg px-3.5 text-sm text-foreground placeholder:text-input-placeholder transition focus-visible:bg-accent-soft";

interface Props {
  id: string;
  email: string;
  currentName: string | null;
  /** The signed-in person renaming themselves. */
  self: boolean;
  onClose: () => void;
}

/** Your own name, or anyone's as root_admin - the server's rule ([0.21.0]). */
export default function RenameDialog({
  id,
  email,
  currentName,
  self,
  onClose,
}: Props) {
  const { showToast } = useToast();
  const rename = useUpdateDisplayName();
  const [name, setName] = useState(currentName ?? "");
  const [error, setError] = useState<string | null>(null);
  const trimmed = name.trim();

  async function onSave() {
    setError(null);
    try {
      await rename.mutateAsync({ id, name: trimmed });
      showToast("Name updated.");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the name.");
    }
  }

  return (
    <Modal
      title={self ? "Change your name" : `Rename ${currentName ?? email}`}
      subtitle={email}
      onClose={onClose}
      busy={rename.isPending}
      footer={
        <>
          <Button
            variant="secondary"
            onClick={onClose}
            disabled={rename.isPending}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            form="rename-form"
            disabled={!trimmed || trimmed === currentName || rename.isPending}
          >
            {rename.isPending ? "Saving…" : "Save"}
          </Button>
        </>
      }
    >
      <form
        id="rename-form"
        onSubmit={(e) => {
          e.preventDefault();
          void onSave();
        }}
      >
        <label className="flex flex-col gap-2">
          <span className="text-xs text-muted-foreground">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            autoFocus
            className={FIELD}
          />
        </label>
      </form>
      {error && (
        <p
          className="mt-4 rounded-md bg-danger-soft px-4 py-3 text-[13px] text-danger"
          role="alert"
        >
          {error}
        </p>
      )}
    </Modal>
  );
}
