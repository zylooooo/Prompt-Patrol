import { useState } from "react";
import { useAuth } from "../hooks/useAuth";
import BatchTab from "../components/BatchTab";
import { hasScreeningAccess } from "../api/checks";
import PageHeader from "../components/ui/PageHeader";
import { usePageTitle } from "../hooks/usePageTitle";
import Page, { PageScroll } from "../components/ui/Page";
import SingleCheckTab from "../components/SingleCheckTab";
import Tabs, { type TabOption } from "../components/ui/Tabs";
import ModelStatusBadge from "../components/ModelStatusBadge";

type TabId = "single" | "batch";

const CHECK_TABS: TabOption<TabId>[] = [
  { value: "single", label: "Single answer" },
  { value: "batch", label: "Batch upload (CSV)" },
];

export default function CheckPage() {
  usePageTitle("Screen New Answers");
  const { user } = useAuth();
  const [tab, setTab] = useState<TabId>("single");

  const unassigned = !user || !hasScreeningAccess(user);

  return (
    <Page>
      <PageHeader
        title="Screen New Answers"
        subtitle="Screen short answers for signs of AI generation."
        actions={unassigned ? undefined : <ModelStatusBadge />}
      />

      {unassigned ? (
        <section className="mt-8 shrink-0 rounded-xl border border-border bg-surface p-12 text-center">
          <p className="text-lg font-medium text-foreground">
            You are not assigned to an instructor yet
          </p>
          <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
            Once an instructor adds you as their teaching assistant, you can
            screen answers for their courses. Ask them to add you, or contact
            your course administrator.
          </p>
        </section>
      ) : (
        <>
          <div className="mt-7 shrink-0">
            <Tabs
              tabs={CHECK_TABS}
              value={tab}
              onChange={setTab}
              ariaLabel="Check mode"
            />
          </div>
          <PageScroll
            className="mt-6"
            role="tabpanel"
            id={`panel-${tab}`}
            aria-labelledby={`tab-${tab}`}
          >
            {tab === "single" ? <SingleCheckTab /> : <BatchTab />}
          </PageScroll>
        </>
      )}
    </Page>
  );
}
