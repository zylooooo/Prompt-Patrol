import { useMemo, useState } from "react";
import DeactivateInstructorDialog from "../components/DeactivateInstructorDialog";
import PageHeader from "../components/PageHeader";
import RelationshipDialog from "../components/RelationshipDialog";
import RowAction from "../components/RowAction";
import Button from "../components/ui/Button";
import TokenMultiSelect from "../components/TokenMultiSelect";
import { useAuth } from "../hooks/useAuth";
import {
  useCreateAccount,
  useSetUserActive,
  useSupervision,
  useUsers,
} from "../hooks/useUsers";
import { usePageTitle } from "../hooks/usePageTitle";
import { useToast } from "../hooks/useToast";
import {
  displayName,
  isActive,
  roleLabel,
  type AppUser,
  type UserRole,
} from "../api/types";

type Filter = "all" | "instructors" | "assistants" | "unassigned";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "instructors", label: "Instructors" },
  { id: "assistants", label: "Teaching assistants" },
  { id: "unassigned", label: "Unassigned" },
];

const HEAD_CELL =
  "py-3 pr-4 text-[11px] font-semibold tracking-[0.09em] text-muted-foreground uppercase";

const FIELD =
  "h-11 rounded-md border border-input-border bg-input-bg px-3.5 text-sm text-foreground placeholder:text-input-placeholder transition focus:outline-hidden focus:ring-2 focus:ring-focus-ring/30";

const SELECT =
  "h-11 rounded-md border border-input-border bg-surface px-3 text-sm transition focus:outline-hidden focus:ring-2 focus:ring-focus-ring/30";

export default function UsersPage() {
  usePageTitle("Users");
  const { user: actor } = useAuth();
  const { showToast } = useToast();
  const { data: users, isPending } = useUsers();
  const { data: links } = useSupervision();
  const createAccount = useCreateAccount();
  const setActive = useSetUserActive();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserRole | "">("");
  const [supervisors, setSupervisors] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{
    id: string;
    message: string;
  } | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [relationship, setRelationship] = useState<{
    subject: AppUser;
    direction: "supervisors" | "assistants";
  } | null>(null);
  const [deactivating, setDeactivating] = useState<AppUser | null>(null);

  const instructors = useMemo(
    () => (users ?? []).filter((u) => u.role === "instructor"),
    [users],
  );

  // derived from the query data so the table reacts when links change. Keyed by
  // the teaching assistant's id, which is what every read below must use.
  const supervisorNames = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const link of links ?? []) {
      const instructor = (users ?? []).find(
        (user) => user.id === link.instructorId,
      );
      if (!instructor) continue;
      map.set(link.taId, [
        ...(map.get(link.taId) ?? []),
        displayName(instructor),
      ]);
    }
    for (const [key, names] of map) map.set(key, [...names].sort());
    return map;
  }, [links, users]);

  function supervisorText(u: AppUser): string {
    if (u.role !== "teaching_assistant") return "·";
    const names = supervisorNames.get(u.id) ?? [];
    if (names.length === 0) return "Unassigned";
    if (names.length === 1) return names[0];
    return `${names[0]} +${names.length - 1}`;
  }

  const visible = useMemo(() => {
    const list = users ?? [];
    if (filter === "instructors")
      return list.filter((u) => u.role === "instructor");
    if (filter === "assistants")
      return list.filter((u) => u.role === "teaching_assistant");
    if (filter === "unassigned") {
      return list.filter(
        (u) =>
          u.role === "teaching_assistant" &&
          (supervisorNames.get(u.id) ?? []).length === 0,
      );
    }
    return list;
  }, [users, filter, supervisorNames]);

  async function onAdd() {
    setError(null);
    try {
      const created = await createAccount.mutateAsync({
        name: name.trim() || undefined,
        email: email.trim(),
        role: role as UserRole,
        supervisorIds: role === "teaching_assistant" ? supervisors : [],
      });
      setName("");
      setEmail("");
      setRole("");
      setSupervisors([]);
      showToast(`${created.email} can now sign in with their SMU account`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not add the account.",
      );
    }
  }

  async function onToggleActive(target: AppUser) {
    setError(null);
    setRowError(null);
    setPending(target.id);
    try {
      await setActive.mutateAsync({ id: target.id, active: !isActive(target) });
      showToast(isActive(target) ? "Account deactivated" : "Account reactivated");
    } catch (err) {
      setRowError({
        id: target.id,
        message:
          err instanceof Error ? err.message : "Could not update the account.",
      });
    } finally {
      setPending(null);
    }
  }

  // deactivating an instructor may strand the people they supervise, so it goes
  // through the decision dialog. Reactivating, and anything on a teaching
  // assistant, has no such consequence and applies directly
  function onStatusClick(target: AppUser) {
    if (isActive(target) && target.role === "instructor") {
      setDeactivating(target);
      return;
    }
    void onToggleActive(target);
  }

  const canSubmit = email.trim() !== "" && role !== "";

  return (
    <>
      <PageHeader
        title="Users"
        subtitle="Provision accounts for instructors and teaching assistants. There is no self-registration."
        showModelStatus={false}
      />

      <section className="mt-8 rounded-xl border border-border bg-surface p-7">
        <p className="text-[11px] font-semibold tracking-[0.09em] text-muted-foreground uppercase">
          Add account
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void onAdd();
          }}
          className="mt-4 flex flex-wrap items-end gap-3"
        >
          <label className="flex flex-col gap-2">
            <span className="text-xs text-muted-foreground">Name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="full name"
              className={`w-48 ${FIELD}`}
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className="text-xs text-muted-foreground">SMU email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@smu.edu.sg"
              className={`w-56 ${FIELD}`}
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className="text-xs text-muted-foreground">Role</span>
            <select
              value={role}
              onChange={(e) => {
                setRole(e.target.value as UserRole | "");
                setSupervisors([]);
              }}
              className={`w-44 ${SELECT} ${
                role ? "text-foreground" : "text-input-placeholder"
              }`}
            >
              <option value="">choose a role</option>
              <option value="instructor">Instructor</option>
              <option value="teaching_assistant">Teaching assistant</option>
            </select>
          </label>

          {/* the supervisor field exists only for the role that can have one */}
          {role === "teaching_assistant" && (
            <div className="flex flex-col gap-2">
              <span className="text-xs text-muted-foreground">
                Supervising instructors
              </span>
              <TokenMultiSelect
                choices={instructors.map((i) => ({
                  value: i.id,
                  label: displayName(i),
                }))}
                selected={supervisors}
                onChange={setSupervisors}
                placeholder="choose instructors"
              />
            </div>
          )}

          <Button
            type="submit"
            size="lg"
            disabled={!canSubmit || createAccount.isPending}
          >
            {createAccount.isPending ? "Adding…" : "Add account"}
          </Button>
        </form>

        <p className="mt-4 text-xs leading-relaxed text-disabled-foreground">
          There is no password to share. The email has to match their SMU
          account exactly, since that is what links the two together when they
          first sign in with Microsoft.
        </p>

        {error && (
          <p
            className="mt-4 rounded-md bg-danger-soft px-4 py-3 text-[13px] text-danger"
            role="alert"
          >
            {error}
          </p>
        )}
      </section>

      <div className="mt-6 flex flex-wrap items-center gap-2">
        {FILTERS.map((option) => (
          <button
            key={option.id}
            type="button"
            onClick={() => setFilter(option.id)}
            aria-pressed={filter === option.id}
            className={`h-9 rounded-md border px-3.5 text-sm transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30 ${
              filter === option.id
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-surface text-muted-foreground hover:text-foreground"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      <section className="mt-5 rounded-xl border border-border bg-surface px-7 py-2">
        {isPending ? (
          <div
            className="flex flex-col gap-3 py-5"
            aria-busy="true"
            aria-label="Loading users"
          >
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-10 animate-pulse rounded-md bg-surface-muted"
              />
            ))}
          </div>
        ) : (
          // narrow windows scroll the table inside the card rather than
          // spilling out of it
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] border-collapse text-left">
              <thead>
                <tr className="border-b border-border">
                  {["Name", "Email", "Role", "Supervisors", "Status", ""].map(
                    (h) => (
                      <th key={h} className={HEAD_CELL}>
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {visible.map((u) => {
                  const isSelf =
                    actor?.email.toLowerCase() === u.email.toLowerCase();
                  const busy = pending === u.id;
                  return (
                    <tr
                      key={u.id}
                      className="border-b border-border last:border-b-0"
                    >
                      <td className="py-4 pr-4 text-sm font-medium text-foreground">
                        {displayName(u)}
                      </td>
                      <td className="py-4 pr-4 font-mono text-xs text-muted-foreground">
                        {u.email}
                      </td>
                      <td className="py-4 pr-4 text-[13px] text-muted-foreground">
                        {roleLabel(u)}
                      </td>
                      <td
                        className={`py-4 pr-4 text-[13px] ${
                          supervisorText(u) === "Unassigned"
                            ? "font-medium text-disabled-foreground"
                            : "text-muted-foreground"
                        }`}
                      >
                        {supervisorText(u)}
                      </td>
                      <td className="py-4 pr-4">
                        <span
                          className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                            isActive(u)
                              ? "bg-human-soft text-human"
                              : "bg-unsure-soft text-unsure"
                          }`}
                        >
                          {isActive(u) ? "Active" : "Deactivated"}
                        </span>
                      </td>
                      <td className="py-4 text-right whitespace-nowrap">
                        {isSelf ? (
                          <span className="pr-2.5 text-[13px] text-disabled-foreground">
                            Your account
                          </span>
                        ) : (
                          <>
                            {u.role === "teaching_assistant" && (
                              <RowAction
                                onClick={() =>
                                  setRelationship({
                                    subject: u,
                                    direction: "supervisors",
                                  })
                                }
                                disabled={busy}
                              >
                                Supervisors
                              </RowAction>
                            )}
                            {u.role === "instructor" && (
                              <RowAction
                                onClick={() =>
                                  setRelationship({
                                    subject: u,
                                    direction: "assistants",
                                  })
                                }
                                disabled={busy}
                              >
                                Teaching assistants
                              </RowAction>
                            )}
                            <RowAction
                              onClick={() => onStatusClick(u)}
                              disabled={busy}
                            >
                              {isActive(u) ? "Deactivate" : "Reactivate"}
                            </RowAction>
                          </>
                        )}
                        {rowError?.id === u.id && (
                          <p className="mt-1 text-xs text-danger" role="alert">
                            {rowError.message}
                          </p>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {visible.length === 0 && (
                  <tr>
                    <td
                      colSpan={6}
                      className="py-10 text-center text-sm text-disabled-foreground"
                    >
                      No accounts match this filter.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {relationship && (
        <RelationshipDialog
          subject={relationship.subject}
          direction={relationship.direction}
          allUsers={users ?? []}
          onClose={() => setRelationship(null)}
        />
      )}

      {deactivating && (
        <DeactivateInstructorDialog
          instructor={deactivating}
          allUsers={users ?? []}
          onClose={() => setDeactivating(null)}
        />
      )}
    </>
  );
}
