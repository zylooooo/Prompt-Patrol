import DataTable, {
  TABLE_ACTION_COLUMN_WIDTH,
  TABLE_STATUS_COLUMN_WIDTH,
  type DataTableColumn,
} from "../components/ui/DataTable";
import {
  useCreateAccount,
  useMyAssistants,
  useSetSupervisor,
} from "../hooks/useUsers";
import { useState } from "react";
import { ApiError } from "../api/client";
import Modal from "../components/ui/Modal";
import { fmtDateOnly } from "../lib/format";
import { useToast } from "../hooks/useToast";
import Button from "../components/ui/Button";
import RowAction from "../components/ui/RowAction";
import ErrorState from "../components/ui/ErrorState";
import PageHeader from "../components/ui/PageHeader";
import { usePageTitle } from "../hooks/usePageTitle";
import { displayName, type AppUser } from "../types";
import Page, { PageFill } from "../components/ui/Page";
import UserStatusChip from "../components/ui/UserStatusChip";
import { SECTION_LABEL } from "../components/ui/section-label";

const FIELD =
  "h-11 rounded-md border border-input-border bg-input-bg px-3.5 text-sm text-foreground placeholder:text-input-placeholder transition focus-visible:bg-accent-soft";

export default function TeachingAssistantsPage() {
  usePageTitle("Manage My Assistants");
  const { showToast } = useToast();
  const { data: assistants, isPending, isError, refetch } = useMyAssistants();
  const createAccount = useCreateAccount();
  const release = useSetSupervisor();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{
    id: string;
    message: string;
  } | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<AppUser | null>(null);

  async function onAdd() {
    setError(null);
    try {
      const created = await createAccount.mutateAsync({
        name: name.trim() || undefined,
        email: email.trim(),
        role: "teaching_assistant",
      });
      setName("");
      setEmail("");
      showToast(`${created.email} can now sign in with their SMU account`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(
          "That email already has an account. Ask your administrator to assign them to you.",
        );
        return;
      }
      setError(
        err instanceof Error ? err.message : "Could not add the account.",
      );
    }
  }

  async function onConfirmRemove() {
    if (!confirmRemove) return;
    const target = confirmRemove;
    setRowError(null);
    setPending(target.id);
    try {
      await release.mutateAsync({ id: target.id, supervisorId: null });
      showToast(`${displayName(target)} removed from your teaching assistants`);
      setConfirmRemove(null);
    } catch (err) {
      setRowError({
        id: target.id,
        message: err instanceof Error ? err.message : "Could not remove them.",
      });
      setConfirmRemove(null);
    } finally {
      setPending(null);
    }
  }

  const list = assistants ?? [];

  const columns: DataTableColumn<AppUser>[] = [
    {
      id: "name",
      header: "Name",
      width: "minmax(0,1.2fr)",
      cell: (ta) => (
        <span className="min-w-0 max-w-[11rem] truncate text-sm font-medium text-foreground">
          {displayName(ta)}
        </span>
      ),
    },
    {
      id: "email",
      header: "Email",
      width: "minmax(0,1.5fr)",
      cell: (ta) => (
        <span className="min-w-0 max-w-[13rem] truncate font-mono text-xs text-muted-foreground">
          {ta.email}
        </span>
      ),
    },
    {
      id: "addedOn",
      header: "Added",
      width: "minmax(0,0.9fr)",
      hideWhenCompact: true,
      cell: (ta) => (
        <span className="truncate text-[13px] text-muted-foreground">
          {fmtDateOnly(ta.createdAt)}
        </span>
      ),
    },
    {
      id: "status",
      header: "Status",
      width: TABLE_STATUS_COLUMN_WIDTH,
      cell: (ta) => <UserStatusChip status={ta.status} />,
    },
    {
      id: "actions",
      header: "",
      width: TABLE_ACTION_COLUMN_WIDTH,
      align: "right",
      cell: (ta) => (
        <RowAction
          onClick={() => setConfirmRemove(ta)}
          disabled={pending === ta.id}
        >
          Remove
        </RowAction>
      ),
    },
  ];

  const erroredAssistant = rowError
    ? list.find((ta) => ta.id === rowError.id)
    : undefined;

  return (
    <Page>
      <PageHeader
        title="Manage My Assistants"
        subtitle="Accounts you supervise."
      />

      <section className="mt-8 shrink-0 rounded-xl bg-surface p-7 shadow-md">
        <p className={SECTION_LABEL}>Add teaching assistant</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void onAdd();
          }}
          className="mt-4 flex flex-wrap items-end gap-3"
        >
          <label className="flex flex-col gap-2">
            <span className="text-xs text-muted-foreground">
              Name (optional)
            </span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Full name"
              className={`w-56 ${FIELD}`}
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className="text-xs text-muted-foreground">SMU email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@smu.edu.sg"
              className={`w-64 ${FIELD}`}
            />
          </label>
          <Button
            type="submit"
            disabled={!email.trim() || createAccount.isPending}
          >
            {createAccount.isPending ? "Adding…" : "Add teaching assistant"}
          </Button>
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

      {isError ? (
        <ErrorState
          className="mt-6"
          title="Could not load your list"
          description="Something went wrong reaching the server. Nothing has changed."
          onRetry={() => void refetch()}
        />
      ) : (
        <PageFill className="mt-6">
          <DataTable<AppUser>
            fillHeight
            columns={columns}
            rows={list}
            getRowId={(ta) => ta.id}
            isLoading={isPending}
            loadingLabel="Loading teaching assistants…"
            emptyState={
              <div>
                <p className="text-lg font-medium text-foreground">
                  No teaching assistants yet
                </p>
                <p className="mx-auto mt-2 max-w-sm text-muted-foreground">
                  Add one above. They will be able to screen answers for your
                  courses.
                </p>
              </div>
            }
          />
          {rowError && (
            <p className="mt-3 shrink-0 text-xs text-danger" role="alert">
              {erroredAssistant ? `${displayName(erroredAssistant)}: ` : ""}
              {rowError.message}
            </p>
          )}
        </PageFill>
      )}

      {confirmRemove && (
        <Modal
          title={`Remove ${displayName(confirmRemove)}`}
          busy={release.isPending}
          onClose={() => setConfirmRemove(null)}
          footer={
            <>
              <Button
                variant="secondary"
                onClick={() => setConfirmRemove(null)}
                disabled={release.isPending}
              >
                Cancel
              </Button>
              <Button
                onClick={() => void onConfirmRemove()}
                disabled={release.isPending}
              >
                {release.isPending ? "Removing…" : "Remove"}
              </Button>
            </>
          }
        >
          <p className="text-sm leading-relaxed text-muted-foreground">
            They keep their account, and it stays active. They stop being able
            to screen answers until an administrator assigns them to an
            instructor again.
          </p>
        </Modal>
      )}
    </Page>
  );
}
