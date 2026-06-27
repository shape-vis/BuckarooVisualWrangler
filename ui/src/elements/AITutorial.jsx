import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { SelectionContext } from "../store/SelectionContext.jsx";
import { useRepair } from "../store/RepairContext.jsx";
import "../styles/AITutorial.css";

export default function AITutorial({ showSignal = 0 }) {
  const { highlightedRowIds } = useContext(SelectionContext);
  const {
    repairPanelOpenTrigger,
    repairPanelCloseTrigger,
    repairWrangleExecutedCount,
  } = useRepair();

  const [visible, setVisible] = useState(true);
  const [repairWorkspaceOpen, setRepairWorkspaceOpen] = useState(false);
  const [exported, setExported] = useState(false);
  const lastOpenTrigger = useRef(repairPanelOpenTrigger);
  const lastCloseTrigger = useRef(repairPanelCloseTrigger);

  useEffect(() => {
    try {
      window.localStorage?.removeItem("buckarooAiTutorialDismissed");
    } catch {
      // Ignore unavailable localStorage; the guide is still visible by default.
    }
  }, []);

  useEffect(() => {
    if (showSignal > 0) setVisible(true);
  }, [showSignal]);

  useEffect(() => {
    if (repairPanelOpenTrigger > lastOpenTrigger.current) {
      setRepairWorkspaceOpen(true);
    }
    lastOpenTrigger.current = repairPanelOpenTrigger;
  }, [repairPanelOpenTrigger]);

  useEffect(() => {
    if (repairPanelCloseTrigger > lastCloseTrigger.current) {
      setRepairWorkspaceOpen(false);
    }
    lastCloseTrigger.current = repairPanelCloseTrigger;
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

    return {
      key: "select",
      target: "plots",
      title: "Welcome to Buckaroo",
      body: "Start by selecting a point or region in a plot. Buckaroo will keep that selection highlighted across the repair workflow.",
      actionLabel: "Skip",
    };
  }, [exported, highlightedRowIds, repairWorkspaceOpen, repairWrangleExecutedCount]);

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
  }

  if (!visible) return null;

  return (
    <aside className={`ai-tutorial ai-tutorial--${step.key}`} aria-live="polite">
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
      <h2>{step.title}</h2>
      <p>{step.body}</p>
      <div className="ai-tutorial-actions">
        <button type="button" onClick={dismiss}>
          {step.actionLabel}
        </button>
      </div>
    </aside>
  );
}
