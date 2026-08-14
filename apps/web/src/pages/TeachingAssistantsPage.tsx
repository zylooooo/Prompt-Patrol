import DataTable, {
  TABLE_ACTION_COLUMN_WIDTH,
  type DataTableColumn,
} from "../components/ui/DataTable";
import {
  findUserByEmail,
  linkedAt,
  lookupForLinking,
  supervisorsOf,
} from "../api/users";
import {
  useCreateAccount,
  useLinkSupervision,
  useMyAssistants,
  useUnlinkSupervision,
} from "../hooks/useUsers";
import { useState } from "react";
import Modal from "../components/ui/Modal";
import { useAuth } from "../hooks/useAuth";
import { fmtDateOnly } from "../lib/format";
import { useToast } from "../hooks/useToast";
import Button from "../components/ui/Button";
import RowAction from "../components/ui/RowAction";
import PageHeader from "../components/ui/PageHeader";
import { usePageTitle } from "../hooks/usePageTitle";
import Page, { PageFill } from "../components/ui/Page";
import { displayName, isActive, type AppUser } from "../types";

const FIELD =
  "h-11 rounded-md border border-input-border bg-input-bg px-3.5 text-sm text-foreground placeholder:text-input-placeholder transition focus:outline-hidden focus:ring-2 focus:ring-focus-ring/30";

export default function TeachingAssistantsPage() {
  usePageTitle("Teaching assistants");
  const { user: session } = useAuth();
  const { showToast } = useToast();
  const { data: assistants, isPending, isError, refetch } = useMyAssistants();
  const createAccount = useCreateAccount();
  const link = useLinkSupervision();
  const unlink = useUnlinkSupervision();
  const actor = session ? findUserByEmail(session.email) : undefined;

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{
    id: string;
    message: string;
  } | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [existing, setExisting] = useState<AppUser | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<AppUser | null>(null);

  function alsoWith(ta: AppUser): string {
    const others = supervisorsOf(ta.id).filter(
      (supervisor) => supervisor.id !== actor?.id,
    );
    return others.length === 0 ? "·" : others.map(displayName).join(", ");
  }

  function addedOn(ta: AppUser): string {
    const iso = actor ? linkedAt(actor.id, ta.id) : undefined;
    return iso ? fmtDateOnly(iso) : "·";
  }

  async function onAdd() {
    if (!session) return;
    setError(null);
    const lookup = lookupForLinking(session, email.trim());
    if (lookup.kind === "linkable") {
      setExisting(lookup.user);
      return;
    }
    if (lookup.kind === "not-eligible") {
      setError(
        "That email belongs to another kind of account. Ask your administrator for help.",
      );
      return;
    }
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
      setError(
        err instanceof Error ? err.message : "Could not add the account.",
      );
    }
  }

  async function onConfirmLink() {
    if (!existing || !actor) return;
    setError(null);
    try {
      await link.mutateAsync({ instructorId: actor.id, taId: existing.id });
      showToast(`${displayName(existing)} added to your teaching assistants`);
      setExisting(null);
      setName("");
      setEmail("");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not link the account.",
      );
      setExisting(null);
    }
  }

  async function onConfirmRemove() {
    if (!confirmRemove || !actor) return;
    const target = confirmRemove;
    setRowError(null);
    setPending(target.id);
    try {
      await unlink.mutateAsync({ instructorId: actor.id, taId: target.id });
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
        <span className="truncate text-sm font-medium text-foreground">
          {displayName(ta)}
        </span>
      ),
    },
    {
      id: "email",
      header: "Email",
      width: "minmax(0,1.5fr)",
      cell: (ta) => (
        <span className="truncate font-mono text-xs text-muted-foreground">
          {ta.email}
        </span>
      ),
    },
    {
      id: "alsoWith",
      header: "Also supervised by",
      width: "minmax(0,1.3fr)",
      hideWhenCompact: true,
      cell: (ta) => (
        <span className="truncate text-[13px] text-muted-foreground">
          {alsoWith(ta)}
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
          {addedOn(ta)}
        </span>
      ),
    },
    {
      id: "status",
      header: "Status",
      width: "minmax(0,0.8fr)",
      cell: (ta) => (
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-medium ${
            isActive(ta)
              ? "bg-human-soft text-human"
              : "bg-unsure-soft text-unsure"
          }`}
        >
          {isActive(ta) ? "Active" : "Deactivated"}
        </span>
      ),
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
        title="Teaching assistants"
        subtitle="Accounts you supervise. They can screen answers for your courses."
      />

      <section className="mt-8 shrink-0 rounded-xl border border-border bg-surface p-7">
        <p className="text-[11px] font-semibold tracking-[0.09em] text-muted-foreground uppercase">
          Add teaching assistant
        </p>
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
              placeholder="full name"
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
            size="lg"
            disabled={!email.trim() || createAccount.isPending}
          >
            {createAccount.isPending ? "Adding…" : "Add teaching assistant"}
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

      {isError ? (
        <section
          className="mt-6 rounded-xl border border-border bg-surface p-12 text-center"
          role="alert"
        >
          <p className="text-lg font-medium text-foreground">
            Could not load your list
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
            Something went wrong reaching the server. Nothing has changed.
          </p>
          <Button
            variant="secondary"
            size="lg"
            className="mt-5"
            onClick={() => void refetch()}
          >
            Try again
          </Button>
        </section>
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
              <div className="p-12 text-center">
                <p className="text-lg font-medium text-foreground">
                  No teaching assistants yet
                </p>
                <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
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

      {existing && (
        <Modal
          title={`${displayName(existing)} already has an account`}
          subtitle={existing.email}
          busy={link.isPending}
          onClose={() => setExisting(null)}
          footer={
            <>
              <Button
                variant="secondary"
                size="lg"
                onClick={() => setExisting(null)}
                disabled={link.isPending}
              >
                Cancel
              </Button>
              <Button
                size="lg"
                onClick={() => void onConfirmLink()}
                disabled={link.isPending}
              >
                {link.isPending ? "Adding…" : "Add to my teaching assistants"}
              </Button>
            </>
          }
        >
          <p className="text-sm leading-relaxed text-muted-foreground">
            Adding them links the existing account to you. No second account is
            created, and their work with other instructors is untouched.
          </p>
          <div className="mt-5 flex items-center justify-between gap-4 rounded-lg border border-border bg-modal-muted px-4 py-3.5">
            <p className="text-sm font-medium text-foreground">
              {displayName(existing)}
            </p>
            <p className="text-[13px] text-muted-foreground">
              {supervisorsOf(existing.id).length === 0
                ? "Currently unassigned"
                : `Currently with ${supervisorsOf(existing.id).map(displayName).join(", ")}`}
            </p>
          </div>
          <p className="mt-4 text-xs leading-relaxed text-disabled-foreground">
            The name on the account stays as it is. Only an administrator can
            rename it.
          </p>
        </Modal>
      )}

      {confirmRemove && (
        <Modal
          title={`Remove ${displayName(confirmRemove)}`}
          busy={unlink.isPending}
          onClose={() => setConfirmRemove(null)}
          footer={
            <>
              <Button
                variant="secondary"
                size="lg"
                onClick={() => setConfirmRemove(null)}
                disabled={unlink.isPending}
              >
                Cancel
              </Button>
              <Button
                size="lg"
                onClick={() => void onConfirmRemove()}
                disabled={unlink.isPending}
              >
                {unlink.isPending ? "Removing…" : "Remove"}
              </Button>
            </>
          }
        >
          <p className="text-sm leading-relaxed text-muted-foreground">
            {supervisorsOf(confirmRemove.id).length > 1
              ? "They keep their account and continue working with their other instructors."
              : "They keep their account. It becomes unassigned and stays active until someone adds them again."}
          </p>
        </Modal>
      )}
    </Page>
  );
}
