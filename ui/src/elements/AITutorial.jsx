import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { SelectionContext } from "../store/SelectionContext.jsx";
import { useRepair } from "../store/RepairContext.jsx";
import "../styles/AITutorial.css";

const DISMISSED_KEY = "buckarooAiTutorialDismissed";

function shouldShowOnLoad() {
  try {
    return window.localStorage?.getItem(DISMISSED_KEY) !== "true";
  } catch {
    return true;
  }
}

export default function AITutorial({ showSignal = 0, selectedAttributes = [] }) {
  const { highlightedRowIds } = useContext(SelectionContext);
  const {
    repairPanelOpenTrigger,
    repairPanelCloseTrigger,
    repairWrangleExecutedCount,
  } = useRepair();

  const [visible, setVisible] = useState(shouldShowOnLoad);
  const [repairWorkspaceOpen, setRepairWorkspaceOpen] = useState(false);
  const [exported, setExported] = useState(false);
  const lastOpenTrigger = useRef(repairPanelOpenTrigger);
  const lastCloseTrigger = useRef(repairPanelCloseTrigger);

  useEffect(() => {
    if (showSignal <= 0) return undefined;
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) setVisible(true);
    });
    return () => {
      cancelled = true;
    };
  }, [showSignal]);

  useEffect(() => {
    const opened = repairPanelOpenTrigger > lastOpenTrigger.current;
    lastOpenTrigger.current = repairPanelOpenTrigger;
    if (!opened) return undefined;
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) setRepairWorkspaceOpen(true);
    });
    return () => {
      cancelled = true;
    };
  }, [repairPanelOpenTrigger]);

  useEffect(() => {
    const closed = repairPanelCloseTrigger > lastCloseTrigger.current;
    lastCloseTrigger.current = repairPanelCloseTrigger;
    if (!closed) return undefined;
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) setRepairWorkspaceOpen(false);
    });
    return () => {
      cancelled = true;
    };
  }, [repairPanelCloseTrigger]);

  useEffect(() => {
    const handleExported = () => setExported(true);
    window.addEventListener("buckaroo:pandas-exported", handleExported);
    return () => window.removeEventListener("buckaroo:pandas-exported", handleExported);
  }, []);

  const step = useMemo(() => {
    const selectedCount = highlightedRowIds?.length || 0;

    if (exported) {
      return {
        key: "done",
        target: null,
        title: "Export downloaded",
        body: "You have the wrangle bundle now. The Provenance Graph, undo, and redo controls are still available as you keep exploring.",
        actionLabel: "Done",
      };
    }

    if (repairWrangleExecutedCount > 0) {
      return {
        key: "export",
        target: "export",
        title: "Repair applied",
        body: "Try Export to download the script that replays your wrangle steps.",
        actionLabel: "Skip",
      };
    }

    if (repairWorkspaceOpen) {
      return {
        key: "workspace",
        target: "repair-workspace",
        title: "Compare the previews",
        body: "Yellow marks the selected data. Pick the preview that matches the fix you want, then execute the wrangle.",
        actionLabel: "Skip",
      };
    }

    if (selectedCount > 0) {
      return {
        key: "repair",
        target: "repair",
        title: "Selection ready",
        body: `${selectedCount} row${selectedCount === 1 ? "" : "s"} selected. Open Repair to preview delete and impute options.`,
        actionLabel: "Skip",
      };
    }

    if (selectedAttributes.length === 0) {
      return {
        key: "choose-column",
        target: "columns",
        title: "Choose a column first",
        body: "Select the checkbox beside a column name. Buckaroo will draw its profile before asking you to select any rows.",
        actionLabel: "Dismiss",
      };
    }

    return {
      key: "select",
      target: "plots",
      title: "Welcome to Buckaroo",
      body: "Start by selecting a point or region in a plot. Buckaroo will keep that selection highlighted across the repair workflow.",
      actionLabel: "Skip",
    };
  }, [exported, highlightedRowIds, repairWorkspaceOpen, repairWrangleExecutedCount, selectedAttributes]);

  useEffect(() => {
    const root = document.documentElement;

    if (!visible || !step.target) {
      root.removeAttribute("data-buckaroo-tutorial-target");
      return undefined;
    }

    root.setAttribute("data-buckaroo-tutorial-target", step.target);
    return () => root.removeAttribute("data-buckaroo-tutorial-target");
  }, [visible, step.target]);

  function dismiss() {
    setVisible(false);
    try {
      window.localStorage?.setItem(DISMISSED_KEY, "true");
    } catch {
      // The guide still closes when browser storage is unavailable.
    }
  }

  if (!visible) return null;

  return (
    <aside
      className={`ai-tutorial ai-tutorial--${step.key}`}
      role="dialog"
      aria-modal="false"
      aria-labelledby="ai-tutorial-title"
    >
      <div className="ai-tutorial-header">
        <span className="ai-tutorial-badge">AI Guide</span>
        <button
          type="button"
          className="ai-tutorial-close"
          onClick={dismiss}
          aria-label="Dismiss tutorial"
        >
          x
        </button>
      </div>
      <div className="ai-tutorial-step">{step.key.replace("-", " ")}</div>
      <h2 id="ai-tutorial-title">{step.title}</h2>
      <p>{step.body}</p>
      <div className="ai-tutorial-actions">
        <button type="button" onClick={dismiss}>
          {step.actionLabel}
        </button>
      </div>
    </aside>
  );
}
