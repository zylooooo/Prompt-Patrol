import Modal from "./ui/Modal";
import Button from "./ui/Button";
import { useState } from "react";
import Dropdown from "./ui/Dropdown";
import { useToast } from "../hooks/useToast";
import { SECTION_LABEL } from "./ui/section-label";
import { useSetSupervisor } from "../hooks/useUsers";
import { displayName, isActive, type AppUser } from "../types";

interface SupervisorDialogProps {
  assistant: AppUser;
  allUsers: AppUser[];
  onClose: () => void;
}

export default function SupervisorDialog({
  assistant,
  allUsers,
  onClose,
}: SupervisorDialogProps) {
  const { showToast } = useToast();
  const setSupervisor = useSetSupervisor();
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(
    assistant.provisionedBy,
  );

  const instructors = allUsers.filter(
    (who) => who.role === "instructor" && isActive(who),
  );
  const current = allUsers.find((who) => who.id === assistant.provisionedBy);
  const dirty = selected !== assistant.provisionedBy;
  const busy = setSupervisor.isPending;

  async function onSave() {
    setError(null);
    try {
      await setSupervisor.mutateAsync({
        id: assistant.id,
        supervisorId: selected,
      });
      const next = instructors.find((who) => who.id === selected);
      showToast(
        next
          ? `${displayName(assistant)} now reports to ${displayName(next)}`
          : `${displayName(assistant)} is now unassigned`,
      );
      onClose();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not save the change.",
      );
    }
  }

  return (
    <Modal
      title={`Supervisor for ${displayName(assistant)}`}
      subtitle={assistant.email}
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
        {assistant.provisionedBy === null ? (
          <p className="text-sm text-disabled-foreground">
            Nobody supervises this account yet, so they cannot screen answers.
          </p>
        ) : (
          <p className="text-sm font-medium text-foreground">
            {current ? displayName(current) : "Unknown account"}
          </p>
        )}
      </div>

      <p className={`mt-5 ${SECTION_LABEL}`}>Supervising instructor</p>
      <div className="mt-2.5">
        <Dropdown<string>
          value={selected}
          onChange={setSelected}
          options={instructors.map((who) => ({
            value: who.id,
            label: displayName(who),
          }))}
          placeholder="Nobody (unassigned)"
          ariaLabel="Supervising instructor"
          emptyLabel="No active instructors"
          resetLabel="Nobody (unassigned)"
          size="lg"
          triggerLeading={false}
          className="w-full"
          measureTriggerLabels={false}
          matchTriggerWidth
        />
      </div>

      <p className="mt-4 text-xs leading-relaxed text-disabled-foreground">
        An assistant reports to one instructor. Leaving them unassigned keeps
        the account active but ends their screening access, and signs them out.
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
