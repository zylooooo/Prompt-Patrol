import {
  displayName,
  isActive,
  type AppUser,
  type DeactivationPlan,
} from "../types";
import Modal from "./ui/Modal";
import Button from "./ui/Button";
import Dropdown from "./ui/Dropdown";
import { useToast } from "../hooks/useToast";
import { useMemo, useState, type ReactNode } from "react";
import { useDeactivateInstructor } from "../hooks/useUsers";

interface Props {
  instructor: AppUser;
  allUsers: AppUser[];
  onClose: () => void;
}

type Mode = DeactivationPlan["mode"];

export default function DeactivateInstructorDialog({
  instructor,
  allUsers,
  onClose,
}: Props) {
  const { showToast } = useToast();
  const deactivate = useDeactivateInstructor();
  const [mode, setMode] = useState<Mode>("reassign");
  const [toId, setToId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const stranded = useMemo(
    () =>
      allUsers.filter(
        (u) =>
          u.role === "teaching_assistant" &&
          u.provisionedBy === instructor.id &&
          u.status !== "deleted",
      ),
    [allUsers, instructor.id],
  );

  const otherInstructors = allUsers.filter(
    (u) => u.role === "instructor" && u.id !== instructor.id && isActive(u),
  );

  async function onConfirm() {
    setError(null);
    setBusy(true);
    try {
      const plan: DeactivationPlan =
        stranded.length === 0
          ? { mode: "leave" }
          : mode === "reassign"
            ? { mode: "reassign", toId }
            : mode === "deactivate"
              ? { mode: "deactivate" }
              : { mode: "leave" };
      const outcome = await deactivate.mutateAsync({ id: instructor.id, plan });
      const detail =
        outcome.reassigned > 0
          ? ` ${outcome.reassigned} teaching assistant${outcome.reassigned === 1 ? "" : "s"} reassigned.`
          : outcome.deactivated > 0
            ? ` ${outcome.deactivated} teaching assistant${outcome.deactivated === 1 ? "" : "s"} deactivated.`
            : outcome.leftUnassigned > 0
              ? ` ${outcome.leftUnassigned} left unassigned.`
              : "";
      showToast(`${displayName(instructor)} deactivated.${detail}`);
      onClose();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not deactivate the account.",
      );
    } finally {
      setBusy(false);
    }
  }

  const blocked = stranded.length > 0 && mode === "reassign" && !toId;

  const option = (
    value: Mode,
    label: string,
    helper?: string,
    extra?: ReactNode,
  ) => (
    <label
      className={`block cursor-pointer rounded-lg border px-3.5 py-3 ${
        mode === value
          ? "border-primary bg-primary-soft focus-within:bg-accent-border/60"
          : "border-border focus-within:bg-accent-soft"
      }`}
    >
      <span className="flex items-start gap-3">
        <input
          type="radio"
          name="plan"
          checked={mode === value}
          onChange={() => setMode(value)}
          className="mt-0.5 h-4 w-4 accent-primary"
        />
        <span>
          <span
            className={`text-sm text-foreground ${mode === value ? "font-medium" : ""}`}
          >
            {label}
          </span>
          {helper && (
            <span className="mt-1 block text-xs leading-relaxed text-disabled-foreground">
              {helper}
            </span>
          )}
        </span>
      </span>
      {mode === value && extra}
    </label>
  );

  return (
    <Modal
      title={`Deactivate ${displayName(instructor)}`}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => void onConfirm()}
            disabled={blocked || busy}
          >
            {busy ? "Deactivating…" : "Deactivate account"}
          </Button>
        </>
      }
    >
      {stranded.length === 0 ? (
        <p className="text-sm leading-relaxed text-muted-foreground">
          This account supervises nobody, so no teaching assistants are
          affected.
        </p>
      ) : (
        <>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {stranded.map(displayName).join(", ")}{" "}
            {stranded.length === 1 ? "reports" : "report"} to this account.
            Choose what happens to them.
          </p>

          <div className="mt-5 flex flex-col gap-1.5">
            {option(
              "reassign",
              "Reassign them to another instructor",
              undefined,
              <span className="mt-3 block" onClick={(e) => e.stopPropagation()}>
                <Dropdown<string>
                  value={toId || null}
                  onChange={(next) => setToId(next ?? "")}
                  options={otherInstructors.map((candidate) => ({
                    value: candidate.id,
                    label: displayName(candidate),
                  }))}
                  placeholder="Choose an instructor"
                  ariaLabel="Instructor to reassign to"
                  emptyLabel="No other active instructors"
                  size="lg"
                  triggerLeading={false}
                  className="w-full"
                  measureTriggerLabels={false}
                  matchTriggerWidth
                />
              </span>,
            )}
            {option(
              "deactivate",
              "Deactivate them as well",
              "Use this when the teaching assistants are leaving too.",
            )}
            {option(
              "leave",
              "Leave them unassigned for now",
              "They keep their accounts and appear under the Unassigned filter until someone assigns them.",
            )}
          </div>
        </>
      )}

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
