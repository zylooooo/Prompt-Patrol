import { useState, type ReactNode } from "react";
import { useAuth } from "../hooks/useAuth";
import BatchTab from "../components/BatchTab";
import { useSearchParams } from "react-router-dom";
import { hasScreeningAccess } from "../api/checks";
import PageHeader from "../components/ui/PageHeader";
import { usePageTitle } from "../hooks/usePageTitle";
import Page, { PageScroll } from "../components/ui/Page";
import SingleCheckTab from "../components/SingleCheckTab";
import Tabs, { type TabOption } from "../components/ui/Tabs";
import UnassignedNotice from "../components/UnassignedNotice";
import ModelStatusBadge from "../components/ModelStatusBadge";

type TabId = "single" | "batch";

const CHECK_TABS: TabOption<TabId>[] = [
  { value: "single", label: "Single answer" },
  { value: "batch", label: "Batch (CSV)" },
];

export default function CheckPage() {
  usePageTitle("Check answers");
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const [tab, setTab] = useState<TabId>(
    searchParams.get("tab") === "batch" ? "batch" : "single",
  );
  // Panels stay mounted once opened and are only hidden, so switching tabs
  // keeps a half-typed answer, a picked CSV and any result on screen. Nothing
  // is written to storage: it lives exactly as long as this page does.
  const [opened, setOpened] = useState<ReadonlySet<TabId>>(
    () => new Set([tab]),
  );

  function selectTab(next: TabId) {
    setTab(next);
    setOpened((prev) => (prev.has(next) ? prev : new Set(prev).add(next)));
  }

  const panel = (id: TabId, content: ReactNode) =>
    opened.has(id) && (
      <PageScroll
        className="mt-6"
        role="tabpanel"
        id={`panel-${id}`}
        aria-labelledby={`tab-${id}`}
        hidden={tab !== id}
      >
        {content}
      </PageScroll>
    );

  const unassigned = !user || !hasScreeningAccess(user);

  return (
    <Page>
      <PageHeader
        title="Check answers"
        subtitle="Check short answers and flag the ones worth a closer look."
        actions={unassigned ? undefined : <ModelStatusBadge />}
      />

      {unassigned ? (
        <UnassignedNotice className="mt-8" />
      ) : (
        <>
          <div className="mt-7 shrink-0">
            <Tabs
              tabs={CHECK_TABS}
              value={tab}
              onChange={selectTab}
              ariaLabel="Check mode"
            />
          </div>
          {panel("single", <SingleCheckTab />)}
          {panel("batch", <BatchTab />)}
        </>
      )}
    </Page>
  );
}
