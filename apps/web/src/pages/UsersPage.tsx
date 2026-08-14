import {
  displayName,
  isActive,
  roleLabel,
  type AppUser,
  type UserRole,
} from "../types";
import {
  useCreateAccount,
  useSetUserActive,
  useSupervision,
  useUsers,
} from "../hooks/useUsers";
import SegmentedToggle, {
  type SegmentedToggleOption,
} from "../components/ui/SegmentedToggle";
import { useMemo, useState } from "react";
import { useAuth } from "../hooks/useAuth";
import Button from "../components/ui/Button";
import { useToast } from "../hooks/useToast";
import RowAction from "../components/ui/RowAction";
import PageHeader from "../components/ui/PageHeader";
import { usePageTitle } from "../hooks/usePageTitle";
import Page, { PageFill } from "../components/ui/Page";
import TokenMultiSelect from "../components/ui/TokenMultiSelect";
import RelationshipDialog from "../components/RelationshipDialog";
import Dropdown, { type DropdownOption } from "../components/ui/Dropdown";
import DataTable, { type DataTableColumn } from "../components/ui/DataTable";
import DeactivateInstructorDialog from "../components/DeactivateInstructorDialog";

type Filter = "all" | "instructors" | "assistants" | "unassigned";

const FILTERS: SegmentedToggleOption<Filter>[] = [
  { value: "all", label: "All" },
  { value: "instructors", label: "Instructors" },
  { value: "assistants", label: "Teaching assistants" },
  { value: "unassigned", label: "Unassigned" },
];

const FIELD =
  "h-11 rounded-md border border-input-border bg-input-bg px-3.5 text-sm text-foreground placeholder:text-input-placeholder transition focus:outline-hidden focus:ring-2 focus:ring-focus-ring/30";

const ROLE_OPTIONS: DropdownOption<UserRole>[] = [
  { value: "instructor", label: "Instructor" },
  { value: "teaching_assistant", label: "Teaching assistant" },
];

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
      showToast(
        isActive(target) ? "Account deactivated" : "Account reactivated",
      );
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

  function onStatusClick(target: AppUser) {
    if (isActive(target) && target.role === "instructor") {
      setDeactivating(target);
      return;
    }
    void onToggleActive(target);
  }

  const canSubmit = email.trim() !== "" && role !== "";

  const columns: DataTableColumn<AppUser>[] = [
    {
      id: "name",
      header: "Name",
      width: "minmax(0,1.2fr)",
      cell: (u) => (
        <span className="truncate text-sm font-medium text-foreground">
          {displayName(u)}
        </span>
      ),
    },
    {
      id: "email",
      header: "Email",
      width: "minmax(0,1.5fr)",
      cell: (u) => (
        <span className="truncate font-mono text-xs text-muted-foreground">
          {u.email}
        </span>
      ),
    },
    {
      id: "role",
      header: "Role",
      width: "minmax(0,1fr)",
      hideWhenCompact: true,
      cell: (u) => (
        <span className="truncate text-[13px] text-muted-foreground">
          {roleLabel(u)}
        </span>
      ),
    },
    {
      id: "supervisors",
      header: "Supervisors",
      width: "minmax(0,1.2fr)",
      hideWhenCompact: true,
      cell: (u) => (
        <span
          className={`truncate text-[13px] ${
            supervisorText(u) === "Unassigned"
              ? "font-medium text-disabled-foreground"
              : "text-muted-foreground"
          }`}
        >
          {supervisorText(u)}
        </span>
      ),
    },
    {
      id: "status",
      header: "Status",
      width: "minmax(0,0.8fr)",
      cell: (u) => (
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-medium ${
            isActive(u)
              ? "bg-human-soft text-human"
              : "bg-unsure-soft text-unsure"
          }`}
        >
          {isActive(u) ? "Active" : "Deactivated"}
        </span>
      ),
    },
    {
      id: "actions",
      header: "",
      width: "minmax(0,1.8fr)",
      align: "right",
      cell: (u) => {
        const isSelf = actor?.email.toLowerCase() === u.email.toLowerCase();
        const busy = pending === u.id;
        if (isSelf) {
          return (
            <span className="pr-2.5 text-[13px] text-disabled-foreground">
              Your account
            </span>
          );
        }
        return (
          <span className="flex items-center justify-end gap-1">
            {u.role === "teaching_assistant" && (
              <RowAction
                onClick={() =>
                  setRelationship({ subject: u, direction: "supervisors" })
                }
                disabled={busy}
              >
                Supervisors
              </RowAction>
            )}
            {u.role === "instructor" && (
              <RowAction
                onClick={() =>
                  setRelationship({ subject: u, direction: "assistants" })
                }
                disabled={busy}
              >
                Teaching assistants
              </RowAction>
            )}
            <RowAction onClick={() => onStatusClick(u)} disabled={busy}>
              {isActive(u) ? "Deactivate" : "Reactivate"}
            </RowAction>
          </span>
        );
      },
    },
  ];

  const erroredUser = rowError
    ? (users ?? []).find((u) => u.id === rowError.id)
    : undefined;

  return (
    <Page>
      <PageHeader
        title="Users"
        subtitle="Provision accounts for instructors and teaching assistants. There is no self-registration."
      />

      <section className="mt-8 shrink-0 rounded-xl border border-border bg-surface p-7">
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

          <div className="flex flex-col gap-2">
            <span className="text-xs text-muted-foreground">Role</span>
            <Dropdown<UserRole>
              value={role === "" ? null : role}
              onChange={(next) => {
                setRole(next ?? "");
                setSupervisors([]);
              }}
              options={ROLE_OPTIONS}
              placeholder="choose a role"
              ariaLabel="Role"
              size="lg"
              triggerLeading={false}
            />
          </div>

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

      <div className="mt-6 shrink-0">
        <SegmentedToggle
          options={FILTERS}
          value={filter}
          onChange={setFilter}
          ariaLabel="Filter accounts"
        />
      </div>

      <PageFill className="mt-5">
        <DataTable<AppUser>
          fillHeight
          columns={columns}
          rows={visible}
          getRowId={(u) => u.id}
          isLoading={isPending}
          loadingLabel="Loading accounts…"
          emptyState={
            <p className="px-3 py-10 text-center text-sm text-disabled-foreground">
              No accounts match this filter.
            </p>
          }
        />
        {rowError && (
          <p className="mt-3 shrink-0 text-xs text-danger" role="alert">
            {erroredUser ? `${displayName(erroredUser)}: ` : ""}
            {rowError.message}
          </p>
        )}
      </PageFill>

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
    </Page>
  );
}
