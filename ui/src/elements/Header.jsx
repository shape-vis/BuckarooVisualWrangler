import {NavButton, IconButton} from "./Buttons.jsx";
import {useContext, useEffect, useState} from "react";
import { ViewContext } from "../store/ViewContext.jsx";
import SettingsModal from "./SettingsModal.jsx";
import SemanticGroupsModal from "../panels/SemanticGroupsModal.jsx";
import { exportPandasScript, resetApp } from "../utils/serverCalls.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import { useLoading } from "../store/LoadingContext.jsx";
import { useRepair } from "../store/RepairContext.jsx";
import "../styles/Header.css"

function TableStatus() {
    const { tableName } = useTableName();
    const { isLoading } = useLoading();

    const match = tableName?.match(/^n(\d+)_(.+)$/);
    const label = match ? `n${match[1]} - ${match[2]}` : tableName || "No table";

    return (
        <div className="table-status">
            <span className={`table-status-dot ${isLoading ? "table-status-dot--loading" : "table-status-dot--ready"}`} />
            <span className="table-status-label">{label}</span>
        </div>
    );
}

export default function Header( { onReset} ) {
  onReset = onReset || (() => {});
  return (
    <div id="header" className="header">
      <h1 onClick={ onReset }>
        Buckaroo Visual Wrangler{" "}
        <img
          src="/images/favicon/favicon-96x96.png"
          height="40"
          alt="Buckaroo Logo"
        />
      </h1>
    </div>
  );
}

export function BuckarooHeader( { onReset, onShowAiGuide } ) {
    onReset = onReset || (() => {});
    onShowAiGuide = onShowAiGuide || (() => {});
    const { activeView, setActiveView, refreshKey } = useContext(ViewContext);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [semanticGroupsOpen, setSemanticGroupsOpen] = useState(false);
    const [exportToast, setExportToast] = useState(null);
    const { busy, hasSelection, handleUndo, handleRedo, triggerRepairSelection } = useRepair();

    useEffect(() => {
        if (!exportToast) return undefined;
        const timer = window.setTimeout(() => setExportToast(null), 3200);
        return () => window.clearTimeout(timer);
    }, [exportToast]);

    const handleBack = async () => {
        await resetApp();
        onReset();
    };

    const handleExportPandas = async () => {
        // Ask Flask for the bundle that replays the current provenance graph
        // state. If the backend says no table/graph is loaded, show that error.
        const result = await exportPandasScript();
        if (!result?.success) {
            alert(result?.error || "Export pandas script failed.");
            return;
        }

        // The bundle is a zip containing buckaroo_export.py plus the helper
        // library it imports. Save it without navigating away from the app.
        const url = URL.createObjectURL(result.blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "buckaroo_export.zip";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        setExportToast({
            id: Date.now(),
            message: "Export downloaded as buckaroo_export.zip.",
        });
        window.dispatchEvent(new CustomEvent("buckaroo:pandas-exported", {
            detail: { fileName: "buckaroo_export.zip" },
        }));
    };

    return (
        <div id="header">
            <h1 onClick={ onReset }>
                Buckaroo Visual Wrangler{" "}
                <img
                    src="/images/favicon/favicon-96x96.png"
                    height="24"
                    alt="Buckaroo Logo"
                />
            </h1>
            <TableStatus />
            <div className="navButtonContainer">
                <NavButton onClick={() => setActiveView('graph')} isSelected={activeView === 'graph'} icon={<img src="/images/icons/pgraphlogo.svg" alt="" className="navButtonSvgIcon" />}>Provenance Graph</NavButton>
                <NavButton onClick={() => setActiveView('plots')} isSelected={activeView === 'plots'} icon={<img src="/images/icons/plotlogo.svg" alt="" className="navButtonSvgIcon" />}> Plots </NavButton>
            </div>
            <div className="headerActions">
                <button
                    className="header-action-btn header-action-btn--export"
                    data-tutorial-target="export"
                    onClick={handleExportPandas}
                    disabled={busy}
                    title="Export Pandas Script"
                >
                    <span className="btn-icon">py</span>
                    <span className="header-action-label">Export</span>
                </button>
                <button
                    className="header-action-btn header-action-btn--semantic"
                    onClick={() => setSemanticGroupsOpen(true)}
                    disabled={busy}
                    title="Open Semantic Groups"
                >
                    <span className="btn-icon">S</span>
                    <span className="header-action-label">Semantic</span>
                </button>
                <button
                    className="header-action-btn"
                    data-tutorial-target="repair"
                    onClick={triggerRepairSelection}
                    disabled={busy || !hasSelection}
                    title="Repair Selection"
                >
                    <img src="/images/icons/repair.svg" alt="" className="btn-svg-icon" />
                    <span className="header-action-label">Repair</span>
                </button>
                <button
                    className="header-action-btn"
                    onClick={handleUndo}
                    disabled={busy}
                    title="Undo"
                >
                    <span className="btn-icon">&#8617;</span>
                    <span className="header-action-label">Undo</span>
                </button>
                <button
                    className="header-action-btn"
                    onClick={handleRedo}
                    disabled={busy}
                    title="Redo"
                >
                    <span className="btn-icon">&#8618;</span>
                    <span className="header-action-label">Redo</span>
                </button>
                <IconButton onClick={onShowAiGuide} title="AI Guide" className="ai-guide-header-button">AI</IconButton>
                <IconButton onClick={() => setSettingsOpen(true)} title="Settings">&#9881;</IconButton>
                <IconButton onClick={handleBack} title="Home">&#8962;</IconButton>
            </div>
            {exportToast && (
                <div className="export-success-toast" role="status" aria-live="polite" key={exportToast.id}>
                    {exportToast.message}
                </div>
            )}
            <SettingsModal visible={settingsOpen} onClose={() => setSettingsOpen(false)} />
            <SemanticGroupsModal
                visible={semanticGroupsOpen}
                onClose={() => setSemanticGroupsOpen(false)}
                refreshKey={refreshKey}
            />
        </div>
    );
}
