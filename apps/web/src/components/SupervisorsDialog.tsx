import { useState } from "react";
import Modal from "./ui/Modal";
import Button from "./ui/Button";
import Dropdown from "./ui/Dropdown";
import { SECTION_LABEL } from "./ui/section-label";
import { useToast } from "../hooks/useToast";
import { useLinkSupervisor, useUnlinkSupervisor } from "../hooks/useUsers";
import { displayName, isActive, type AppUser } from "../types";

interface Props {
  assistant: AppUser;
  allUsers: AppUser[];
  onClose: () => void;
}

/**
 * A TA can have any number of supervisors ([0.21.0]), so this edits a list,
 * not a single value. Each change is its own request and applies at once -
 * there is nothing to "save", and a half-applied batch can't happen.
 */
export default function SupervisorsDialog({
  assistant,
  allUsers,
  onClose,
}: Props) {
  const { showToast } = useToast();
  const link = useLinkSupervisor();
  const unlink = useUnlinkSupervisor();
  // Local copy of the links so the list updates from each response without
  // waiting for the roster refetch.
  const [supervisorIds, setSupervisorIds] = useState(assistant.supervisorIds);
  const [toAdd, setToAdd] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The dialog's own in-flight flag. isPending stays true until the roster
  // refetch after a change settles, and a button disabled on it swallows
  // clicks without a word.
  const [busy, setBusy] = useState(false);

  const byId = new Map(allUsers.map((u) => [u.id, u]));
  const nameOf = (id: string) => {
    const who = byId.get(id);
    return who ? displayName(who) : "Unknown account";
  };
  const candidates = allUsers.filter(
    (u) =>
      u.role === "instructor" && isActive(u) && !supervisorIds.includes(u.id),
  );
  const ta = displayName(assistant);

  async function run(
    change: () => Promise<AppUser>,
    message: string,
  ): Promise<void> {
    setError(null);
    setBusy(true);
    try {
      setSupervisorIds((await change()).supervisorIds);
      showToast(message);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not save the change.",
      );
    } finally {
      setBusy(false);
    }
  }

  function onRemove(instructorId: string) {
    void run(
      () => unlink.mutateAsync({ taId: assistant.id, instructorId }),
      `${ta} removed from ${nameOf(instructorId)}'s team.`,
    );
  }

  function onAdd() {
    if (!toAdd) {
      setError("Choose an instructor to add first.");
      return;
    }
    const instructorId = toAdd;
    setToAdd(null);
    void run(
      () => link.mutateAsync({ taId: assistant.id, instructorId }),
      `${ta} added to ${nameOf(instructorId)}'s team.`,
    );
  }

  return (
    <Modal
      title={`Supervisors for ${ta}`}
      subtitle={assistant.email}
      onClose={onClose}
      busy={busy}
      footer={
        <Button onClick={onClose} disabled={busy}>
          Done
        </Button>
      }
    >
      <p className={SECTION_LABEL}>Current</p>
      <div className="mt-2.5 rounded-lg border border-border bg-modal-muted">
        {supervisorIds.length === 0 ? (
          <p className="px-4 py-3.5 text-sm text-disabled-foreground">
            Nobody supervises this account, so they can't screen answers.
          </p>
        ) : (
          <ul
            aria-label="Current supervisors"
            className="divide-y divide-border"
          >
            {supervisorIds.map((id) => (
              <li
                key={id}
                className="flex items-center justify-between gap-3 px-4 py-2.5"
              >
                <span className="min-w-0 truncate text-sm font-medium text-foreground">
                  {nameOf(id)}
                </span>
                {/* TextButton takes neither disabled nor aria-label, so this
                    repeats its look (TEXT_BASE, primary tone) on a plain button. */}
                <button
                  type="button"
                  onClick={() => onRemove(id)}
                  disabled={busy}
                  aria-label={`Remove ${nameOf(id)}`}
                  className="shrink-0 rounded-sm text-sm text-primary underline-offset-2 transition-colors hover:underline focus-visible:underline disabled:text-disabled-foreground disabled:no-underline"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className={`mt-5 ${SECTION_LABEL}`}>Add a supervisor</p>
      <div className="mt-2.5 flex items-center gap-2">
        {/* Dropdown puts className on its trigger, not its wrapper, so the
            wrapper is what stretches across the row. */}
        <div className="min-w-0 flex-1">
          <Dropdown<string>
            value={toAdd}
            onChange={setToAdd}
            options={candidates.map((who) => ({
              value: who.id,
              label: displayName(who),
            }))}
            placeholder="Choose an instructor"
            ariaLabel="Instructor to add"
            emptyLabel="No other active instructors"
            size="lg"
            triggerLeading={false}
            className="w-full"
            measureTriggerLabels={false}
            matchTriggerWidth
          />
        </div>
        <Button variant="secondary" onClick={onAdd} disabled={busy}>
          Add
        </Button>
      </div>

      <p className="mt-4 text-xs leading-relaxed text-disabled-foreground">
        Changes apply straight away. Removing the last supervisor signs them
        out.
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
