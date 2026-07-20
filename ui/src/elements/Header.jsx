import {NavButton, IconButton} from "./Buttons.jsx";
import {useContext, useState} from "react";
import { ViewContext } from "../pages/Buckaroo.jsx";
import SettingsModal from "./SettingsModal.jsx";
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

export function BuckarooHeader( { onReset} ) {
    onReset = onReset || (() => {});
    const { activeView, setActiveView } = useContext(ViewContext);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const { busy, hasSelection, handleUndo, handleRedo, triggerRepairSelection } = useRepair();

    const handleBack = async () => {
        await resetApp();
        onReset();
    };

    const handleExportPandas = async () => {
        // Ask Flask for the script that replays the current provenance graph
        // state. If the backend says no table/graph is loaded, show that error.
        const result = await exportPandasScript();
        if (!result?.success) {
            alert(result?.error || "Export pandas script failed.");
            return;
        }

        // Convert the returned script text into a downloadable .py file without
        // navigating away from the app.
        const blob = new Blob([result.script], { type: "text/x-python;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "buckaroo_export.py";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
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
                <NavButton onClick={() => setActiveView('both')} isSelected={activeView === 'both'} icon={<img src="images/icons/both.svg" alt="" className="navButtonSvgIcon" /> } >Both</NavButton>
                <NavButton onClick={() => setActiveView('graph')} isSelected={activeView === 'graph'} icon={<img src="/images/icons/pgraphlogo.svg" alt="" className="navButtonSvgIcon" />}>Provenance Graph</NavButton>
                <NavButton onClick={() => setActiveView('plots')} isSelected={activeView === 'plots'} icon={<img src="/images/icons/plotlogo.svg" alt="" className="navButtonSvgIcon" />}> Plots </NavButton>
            </div>
            <div className="headerActions">
                <button
                    className="header-action-btn"
                    onClick={triggerRepairSelection}
                    disabled={busy || !hasSelection}
                    title="Repair Selection"
                >
                    <img src="/images/icons/repair.svg" alt="" className="btn-svg-icon" />
                    Repair
                </button>
                <button
                    className="header-action-btn"
                    onClick={handleUndo}
                    disabled={busy}
                    title="Undo"
                >
                    <span className="btn-icon">&#8617;</span>
                    Undo
                </button>
                <button
                    className="header-action-btn"
                    onClick={handleRedo}
                    disabled={busy}
                    title="Redo"
                >
                    <span className="btn-icon">&#8618;</span>
                    Redo
                </button>
                <button
                    className="header-action-btn"
                    onClick={handleExportPandas}
                    disabled={busy}
                    title="Export Pandas Script"
                >
                    <span className="btn-icon">py</span>
                    Export
                </button>
                <IconButton onClick={() => setSettingsOpen(true)} title="Settings">&#9881;</IconButton>
                <IconButton onClick={handleBack} title="Home">&#8962;</IconButton>
            </div>
            <SettingsModal visible={settingsOpen} onClose={() => setSettingsOpen(false)} />
        </div>
    );
}
