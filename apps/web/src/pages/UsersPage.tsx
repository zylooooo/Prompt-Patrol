import SearchInput from "../components/ui/SearchInput";
import SegmentedToggle, {
  type SegmentedToggleOption,
} from "../components/ui/SegmentedToggle";
import {
  canReactivate,
  displayName,
  isActive,
  isPending as isPendingInvite,
  roleLabel,
  type AppUser,
  type UserRole,
} from "../types";
import {
  useCreateAccount,
  useDeleteUser,
  useResendInvite,
  useSetUserActive,
  useUsers,
} from "../hooks/useUsers";
import DataTable, {
  TABLE_ACTIONS_COMPACT_COLUMN_WIDTH,
  TABLE_STATUS_COLUMN_WIDTH,
  type DataTableColumn,
} from "../components/ui/DataTable";
import { useMemo, useState } from "react";
import { ApiError } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import Button from "../components/ui/Button";
import ErrorState from "../components/ui/ErrorState";
import { useToast } from "../hooks/useToast";
import RowAction from "../components/ui/RowAction";
import EmailTypoHint from "../components/ui/EmailTypoHint";
import FormNotice from "../components/ui/FormNotice";
import { useEmailTypoGuard } from "../hooks/useEmailTypoGuard";
import RowActionMenu, {
  type RowActionMenuItem,
} from "../components/ui/RowActionMenu";
import PageHeader from "../components/ui/PageHeader";
import { usePageTitle } from "../hooks/usePageTitle";
import Page, { PageFill } from "../components/ui/Page";
import UserStatusChip from "../components/ui/UserStatusChip";
import { SECTION_LABEL } from "../components/ui/section-label";
import ConfirmDeleteDialog from "../components/ConfirmDeleteDialog";
import Dropdown, { type DropdownOption } from "../components/ui/Dropdown";
import DeactivateReasonDialog from "../components/DeactivateReasonDialog";
import DeactivateInstructorDialog from "../components/DeactivateInstructorDialog";
import ChangeRoleDialog from "../components/ChangeRoleDialog";

type Filter =
  "all" | "instructors" | "assistants" | "unassigned" | "pending" | "deleted";

const FILTER_LABELS: Record<Filter, string> = {
  all: "All",
  instructors: "Instructors",
  assistants: "Teaching Assistants",
  unassigned: "Unassigned",
  pending: "Pending",
  deleted: "Deleted",
};

// Deleted accounts are a record, not part of the working roster: only the
// Deleted filter shows them.
const live = (match: (u: AppUser) => boolean) => (u: AppUser) =>
  u.status !== "deleted" && match(u);

const FILTER_MATCHERS: Record<Filter, (u: AppUser) => boolean> = {
  all: live(() => true),
  instructors: live((u) => u.role === "instructor"),
  assistants: live((u) => u.role === "teaching_assistant"),
  unassigned: live(
    (u) => u.role === "teaching_assistant" && u.supervisorIds.length === 0,
  ),
  pending: live(isPendingInvite),
  deleted: (u) => u.status === "deleted",
};

const FILTER_EMPTY: Record<Filter, string> = {
  all: "No accounts yet. Add one above.",
  instructors: "No instructors yet.",
  assistants: "No teaching assistants yet.",
  unassigned: "No unassigned teaching assistants. Everyone has a supervisor.",
  pending: "No pending invites. Everyone has signed in.",
  deleted: "No deleted accounts.",
};

const FIELD =
  "h-11 rounded-md border border-input-border bg-input-bg px-3.5 text-sm text-foreground placeholder:text-input-placeholder transition focus-visible:bg-accent-soft";

const ROLE_OPTIONS: DropdownOption<UserRole>[] = [
  { value: "instructor", label: "Instructor" },
  { value: "teaching_assistant", label: "Teaching Assistant" },
];

export default function UsersPage() {
  usePageTitle("Manage All Accounts");
  const { user: actor } = useAuth();
  const { showToast } = useToast();
  const { data: users, isPending, isError, refetch } = useUsers();
  const createAccount = useCreateAccount();
  const setActive = useSetUserActive();
  const removeUser = useDeleteUser();
  const resendInvite = useResendInvite();
  const isRootAdmin = actor?.role === "root_admin";

  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserRole | "">("");
  const [supervisorId, setSupervisorId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<AppUser | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [deactivating, setDeactivating] = useState<AppUser | null>(null);
  const [reasoning, setReasoning] = useState<AppUser | null>(null);
  const [changingRole, setChangingRole] = useState<AppUser | null>(null);

  const instructors = useMemo(
    () => (users ?? []).filter((u) => u.role === "instructor"),
    [users],
  );

  function supervisorNames(u: AppUser): string[] {
    return u.supervisorIds.map((id) => {
      const supervisor = (users ?? []).find((who) => who.id === id);
      return supervisor ? displayName(supervisor) : "Unknown account";
    });
  }

  function supervisorText(u: AppUser): string {
    if (u.role !== "teaching_assistant") return "·";
    const names = supervisorNames(u);
    if (names.length === 0) return "Unassigned";
    return names.length === 1 ? names[0] : `${names[0]} +${names.length - 1}`;
  }

  const filterOptions = useMemo<SegmentedToggleOption<Filter>[]>(
    () =>
      (Object.keys(FILTER_LABELS) as Filter[]).map((value) => ({
        value,
        label: FILTER_LABELS[value],
        count: (users ?? []).filter(FILTER_MATCHERS[value]).length,
      })),
    [users],
  );

  const trimmedQuery = query.trim().toLowerCase();
  const visible = useMemo(
    () =>
      (users ?? [])
        .filter(FILTER_MATCHERS[filter])
        .filter(
          (u) =>
            !trimmedQuery ||
            displayName(u).toLowerCase().includes(trimmedQuery) ||
            u.email.toLowerCase().includes(trimmedQuery),
        ),
    [users, filter, trimmedQuery],
  );

  const typo = useEmailTypoGuard(email, setEmail);

  async function onAdd() {
    if (!typo.check()) return;
    setError(null);
    setEmailError(null);
    try {
      const created = await createAccount.mutateAsync({
        email: email.trim(),
        role: role as UserRole,
        supervisorId: role === "teaching_assistant" ? supervisorId : null,
      });
      setEmail("");
      setRole("");
      setSupervisorId(null);
      showToast(
        `${created.email} added. They will get an email with a link to set their password.`,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setEmailError(
          "That email already has an account. Find them in the list below.",
        );
        return;
      }
      setError(
        err instanceof Error ? err.message : "Could not add the account.",
      );
    }
  }

  function rowFailed(verb: string, target: AppUser, err: unknown) {
    const reason = err instanceof Error ? err.message : "Try again.";
    showToast(`Couldn't ${verb} ${displayName(target)}. ${reason}`, {
      tone: "error",
    });
  }

  async function applyActive(
    target: AppUser,
    active: boolean,
    reason?: string,
  ) {
    setError(null);
    setPending(target.id);
    try {
      await setActive.mutateAsync({ id: target.id, active, reason });
      const name = displayName(target);
      if (active) {
        showToast(`${name} reactivated`);
      } else {
        // Deactivating is reversible, so it fires at once and offers Undo
        // rather than asking first. Instructors are the exception: their
        // assistants need a decision, which is the dialog.
        showToast(`${name} deactivated`, {
          action: {
            label: "Undo",
            onClick: () => void applyActive(target, true),
          },
        });
      }
    } catch (err) {
      rowFailed(active ? "reactivate" : "deactivate", target, err);
    } finally {
      setPending(null);
    }
  }

  async function onResendInvite(target: AppUser) {
    try {
      await resendInvite.mutateAsync(target.id);
      showToast(`Invite resent to ${target.email}.`);
    } catch {
      showToast(`Couldn't resend the invite to ${target.email}. Try again.`, {
        tone: "error",
      });
    }
  }

  function onStatusClick(target: AppUser) {
    if (isActive(target) && target.role === "instructor") {
      setDeactivating(target);
      return;
    }
    if (isActive(target)) {
      setReasoning(target);
      return;
    }
    void applyActive(target, !isActive(target));
  }

  const canSubmit = email.trim() !== "" && role !== "";

  const columns: DataTableColumn<AppUser>[] = [
    {
      id: "name",
      header: "Name",
      width: "minmax(0,1.2fr)",
      cell: (u) => (
        <span
          className={`min-w-0 max-w-[11rem] truncate text-sm font-medium text-foreground ${isActive(u) ? "" : "opacity-70"}`}
        >
          {displayName(u)}
        </span>
      ),
    },
    {
      id: "email",
      header: "Email",
      width: "minmax(0,1.5fr)",
      cell: (u) => (
        <span
          title={u.email}
          className={`min-w-0 max-w-[13rem] truncate font-mono text-xs text-muted-foreground ${isActive(u) ? "" : "opacity-70"}`}
        >
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
      id: "supervisor",
      header: "Supervisor",
      width: "minmax(0,1.2fr)",
      hideWhenCompact: true,
      cell: (u) => (
        <span
          title={supervisorNames(u).join(", ") || undefined}
          className={`min-w-0 max-w-[11rem] truncate text-[13px] ${
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
      width: TABLE_STATUS_COLUMN_WIDTH,
      cell: (u) => <UserStatusChip user={u} />,
    },
    {
      id: "actions",
      header: "Actions",
      width: TABLE_ACTIONS_COMPACT_COLUMN_WIDTH,
      align: "right",
      cell: (u) => {
        const isSelf = actor?.email.toLowerCase() === u.email.toLowerCase();
        const busy = pending === u.id;
        if (isSelf) {
          return (
            <span className="pr-2.5 text-[13px] text-disabled-foreground font-bold">
              You
            </span>
          );
        }
        if (u.status === "deleted") return null;

        const menuItems: RowActionMenuItem[] = [];
        // A pending row's next step is re-sending the invite, so that is the
        // inline action and Deactivate moves into the menu.
        const invitePending = isPendingInvite(u);
        if (isRootAdmin && u.role !== "root_admin") {
          menuItems.push({
            label: "Change role",
            onClick: () => setChangingRole(u),
          });
        }
        if (invitePending) {
          menuItems.push({
            label: "Deactivate",
            onClick: () => onStatusClick(u),
          });
        }
        if (isRootAdmin) {
          menuItems.push({
            label: "Delete account",
            onClick: () => setDeleting(u),
            destructive: true,
          });
        }

        return (
          <span className="flex items-center justify-end gap-1">
            {invitePending ? (
              <RowAction
                onClick={() => void onResendInvite(u)}
                disabled={busy || resendInvite.isPending}
              >
                Resend invite
              </RowAction>
            ) : (
              <RowAction onClick={() => onStatusClick(u)} disabled={busy}>
                {canReactivate(u) ? "Reactivate" : "Deactivate"}
              </RowAction>
            )}
            <RowActionMenu
              items={menuItems}
              ariaLabel={`More actions for ${displayName(u)}`}
              disabled={busy}
            />
          </span>
        );
      },
    },
  ];

  // A failed background refetch keeps the roster we already have on screen;
  // only a first load with nothing to show is an error state.
  const loadFailed = isError && !users;

  return (
    <Page>
      <PageHeader
        title="Manage All Accounts"
        subtitle="Provision accounts for instructors and teaching assistants."
      />

      <section className="mt-8 shrink-0 rounded-xl bg-surface p-7 shadow-md">
        <p className={SECTION_LABEL}>Add account</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void onAdd();
          }}
          className="mt-4 flex flex-wrap items-end gap-3"
        >
          <label className="flex flex-col gap-2">
            <span className="text-xs text-muted-foreground">SMU email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setEmailError(null);
              }}
              placeholder="name@smu.edu.sg"
              aria-invalid={emailError ? true : undefined}
              aria-describedby={
                emailError
                  ? "add-email-error"
                  : typo.suggestion
                    ? "add-email-hint"
                    : undefined
              }
              className={`w-56 ${FIELD}`}
            />
          </label>

          <div className="flex flex-col gap-2">
            <span className="text-xs text-muted-foreground">Role</span>
            <Dropdown<UserRole>
              value={role === "" ? null : role}
              onChange={(next) => {
                setRole(next ?? "");
                setSupervisorId(null);
              }}
              options={ROLE_OPTIONS}
              placeholder="Choose a role"
              ariaLabel="Role"
              size="lg"
              triggerLeading={false}
            />
          </div>

          {role === "teaching_assistant" && (
            <div className="flex flex-col gap-2">
              <span className="text-xs text-muted-foreground">
                Supervising instructor
              </span>
              <Dropdown<string>
                value={supervisorId}
                onChange={setSupervisorId}
                options={instructors
                  .filter(isActive)
                  .map((i) => ({ value: i.id, label: displayName(i) }))}
                placeholder="Leave unassigned"
                ariaLabel="Supervising instructor"
                emptyLabel="No active instructors"
                size="lg"
                triggerLeading={false}
              />
            </div>
          )}

          <Button
            type="submit"
            disabled={!canSubmit || createAccount.isPending}
          >
            {createAccount.isPending ? "Adding…" : "Add account"}
          </Button>
          {(typo.suggestion || emailError) && (
            <div className="flex basis-full flex-col gap-1.5">
              <EmailTypoHint
                suggestion={typo.suggestion}
                onUse={typo.applySuggestion}
                onKeep={typo.keepAsTyped}
              />
              {emailError && (
                <FormNotice tone="error" id="add-email-error" role="alert">
                  {emailError}
                </FormNotice>
              )}
            </div>
          )}
        </form>

        {error && (
          <p
            className="mt-4 rounded-md bg-danger-soft px-4 py-3 text-[13px] text-danger"
            role="alert"
          >
            {error}
          </p>
        )}
      </section>

      {loadFailed ? (
        <ErrorState
          className="mt-6"
          title="Could not load accounts"
          description="Something went wrong reaching the server. Nothing has changed."
          onRetry={() => void refetch()}
        />
      ) : (
        <>
          <div className="mt-7 flex shrink-0 flex-wrap items-center gap-2">
            <SearchInput
              value={query}
              onChange={setQuery}
              placeholder="Search name or email"
              ariaLabel="Search accounts"
              wrapperClassName="w-64"
            />
            <SegmentedToggle
              options={filterOptions}
              value={filter}
              onChange={setFilter}
              ariaLabel="Filter accounts"
              indicatorClassName="bg-primary-soft"
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
                <div>
                  <p className="text-muted-foreground">
                    {trimmedQuery
                      ? `No accounts match "${query.trim()}".`
                      : FILTER_EMPTY[filter]}
                  </p>
                  {(trimmedQuery || filter !== "all") && (
                    <Button
                      variant="secondary"
                      className="mt-4"
                      onClick={() => {
                        setQuery("");
                        setFilter("all");
                      }}
                    >
                      Show all accounts
                    </Button>
                  )}
                </div>
              }
            />
          </PageFill>
        </>
      )}

      {deactivating && (
        <DeactivateInstructorDialog
          instructor={deactivating}
          allUsers={users ?? []}
          onClose={() => setDeactivating(null)}
        />
      )}

      {reasoning && (
        <DeactivateReasonDialog
          user={reasoning}
          busy={pending === reasoning.id}
          onClose={() => setReasoning(null)}
          onConfirm={(reason) => {
            const target = reasoning;
            void applyActive(target, false, reason).then(() =>
              setReasoning(null),
            );
          }}
        />
      )}

      {changingRole && (
        <ChangeRoleDialog
          user={changingRole}
          onClose={() => setChangingRole(null)}
        />
      )}

      <ConfirmDeleteDialog
        user={deleting}
        onClose={() => setDeleting(null)}
        onConfirm={(target) => {
          setDeleting(null);
          setPending(target.id);
          void removeUser
            .mutateAsync(target.id)
            .then(() => showToast(`${displayName(target)} deleted.`))
            .catch((err: unknown) => rowFailed("delete", target, err))
            .finally(() => setPending(null));
        }}
      />
    </Page>
  );
}
