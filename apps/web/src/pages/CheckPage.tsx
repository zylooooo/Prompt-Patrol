import { useState } from "react";
import Tabs from "../components/Tabs";
import { useAuth } from "../hooks/useAuth";
import BatchTab from "../components/BatchTab";
import PageHeader from "../components/PageHeader";
import { hasScreeningAccess } from "../api/checks";
import { usePageTitle } from "../hooks/usePageTitle";
import SingleCheckTab from "../components/SingleCheckTab";

type TabId = "single" | "batch";

export default function CheckPage() {
  usePageTitle("Check answers");
  const { user } = useAuth();
  const [tab, setTab] = useState<TabId>("single");

  const unassigned = !user || !hasScreeningAccess(user);

  return (
    <>
      <PageHeader
        title="Check answers"
        subtitle="Screen short answers for signs of AI generation."
        showModelStatus={!unassigned}
      />

      {unassigned ? (
        <section className="mt-8 rounded-xl border border-border bg-surface p-12 text-center">
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
          <div className="mt-7">
            <Tabs
              tabs={[
                { id: "single", label: "Single answer" },
                { id: "batch", label: "Batch upload (CSV)" },
              ]}
              active={tab}
              onChange={setTab}
            />
          </div>
          <div
            className="mt-6"
            role="tabpanel"
            id={`panel-${tab}`}
            aria-labelledby={`tab-${tab}`}
          >
            {tab === "single" ? <SingleCheckTab /> : <BatchTab />}
          </div>
        </>
      )}
    </>
  );
}
