import Modal from "./ui/Modal";
import Button from "./ui/Button";
import { useState } from "react";
import Dropdown, { type DropdownOption } from "./ui/Dropdown";
import { useToast } from "../hooks/useToast";
import { SECTION_LABEL } from "./ui/section-label";
import { useChangeUserRole } from "../hooks/useUsers";
import { displayName, roleLabel, type AppUser, type UserRole } from "../types";

const ROLE_OPTIONS: DropdownOption<Exclude<UserRole, "root_admin">>[] = [
  { value: "instructor", label: "Instructor" },
  { value: "teaching_assistant", label: "Teaching Assistant" },
];

interface ChangeRoleDialogProps {
  user: AppUser;
  onClose: () => void;
}

export default function ChangeRoleDialog({
  user,
  onClose,
}: ChangeRoleDialogProps) {
  const { showToast } = useToast();
  const changeRole = useChangeUserRole();
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Exclude<UserRole, "root_admin">>(
    user.role === "root_admin" ? "instructor" : user.role,
  );

  const dirty = selected !== user.role;
  const busy = changeRole.isPending;

  async function onSave() {
    setError(null);
    try {
      await changeRole.mutateAsync({ id: user.id, role: selected });
      showToast(`${displayName(user)} is now ${roleLabel({ ...user, role: selected })}`);
      onClose();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not save the change.",
      );
    }
  }

  return (
    <Modal
      title={`Role for ${displayName(user)}`}
      subtitle={user.email}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void onSave()} disabled={!dirty || busy}>
            {busy ? "Saving…" : "Save changes"}
          </Button>
        </>
      }
    >
      <p className={SECTION_LABEL}>Current</p>
      <div className="mt-2.5 rounded-lg border border-border bg-modal-muted px-4 py-3.5">
        <p className="text-sm font-medium text-foreground">
          {roleLabel(user)}
        </p>
      </div>

      <p className={`mt-5 ${SECTION_LABEL}`}>New role</p>
      <div className="mt-2.5">
        <Dropdown<Exclude<UserRole, "root_admin">>
          value={selected}
          onChange={(next) => next && setSelected(next)}
          options={ROLE_OPTIONS}
          placeholder="Choose a role"
          ariaLabel="New role"
          size="lg"
          triggerLeading={false}
          className="w-full"
          measureTriggerLabels={false}
          matchTriggerWidth
        />
      </div>

      <p className="mt-4 text-xs leading-relaxed text-disabled-foreground">
        This is recorded as its own audited action, separately from anything
        else changed on this account.
      </p>

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
