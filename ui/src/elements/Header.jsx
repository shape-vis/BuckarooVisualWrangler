import {NavButton, IconButton} from "./Buttons.jsx";
import {useContext, useState} from "react";
import { ViewContext } from "../pages/Buckaroo.jsx";
import SettingsModal from "./SettingsModal.jsx";
import { resetApp } from "../utils/serverCalls.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import { useLoading } from "../store/LoadingContext.jsx";
import { CANDIDATE_LOCKED, useRepair } from "../store/RepairContext.jsx";
import { usePgraph } from "../store/PGraphContext.jsx";
import { useCompare } from "../store/CompareContext.jsx";
import { useAISuggestions } from "../store/AISuggestionsContext.jsx";
import { aiAvailability } from "../store/aiAvailability.js";
import { baseName, nodeName } from "../utils/comparison.js";
import "../styles/Header.css"

function TableStatus() {
    const { tableName } = useTableName();
    const { isLoading } = useLoading();

    // The node's label - n2b, or a staged candidate's c7 - then the uploaded file's name
    const base = baseName(tableName);
    const label = base ? `${nodeName(tableName)} - ${base}` : tableName || "No table";

    return (
        <div className="table-status">
            <span className={`table-status-dot ${isLoading ? "table-status-dot--loading" : "table-status-dot--ready"}`} />
            <span className="table-status-label" title={label}>{label}</span>
        </div>
    );
}

// The app's name and logo; clicking it goes back to the start
function AppTitle( { onReset, logoHeight } ) {
    return (
        <h1 onClick={ onReset }>
            Buckaroo Visual Wrangler{" "}
            <img
                src="/images/favicon/favicon-96x96.png"
                height={logoHeight}
                alt="Buckaroo Logo"
            />
        </h1>
    );
}

export default function Header( { onReset = () => {} } ) {
  return (
    <div id="header" className="header">
      <AppTitle onReset={onReset} logoHeight="40" />
    </div>
  );
}

export function BuckarooHeader( { onReset = () => {} } ) {
    const { openViews, toggleView, openView } = useContext(ViewContext);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const { busy, hasSelection, handleUndo, handleRedo, triggerRepairSelection, repairLocked } = useRepair();
    const { tableName } = useTableName();

    /* The two nodes paired in the graph, if any. The pair is copied when the comparison opens, so it keeps
       comparing what was clicked even if the graph's selection moves on underneath it. */
    const { comparisonPair, openSupportWindow, currentIsCandidate, graphMode } = usePgraph();
    const { openCompare } = useCompare();

    /* The AI's repairs for the current node, as its own AI button asks for them - and refused for the same
       reasons. They are staged as candidates in the graph, so asking opens the graph if it is closed. */
    const ai = useAISuggestions();
    const aiState = aiAvailability({
        configured: ai?.configured,
        locked: currentIsCandidate,
        analysing: graphMode === "analysis",
        busy: ai?.busy,
    });
    const askAI = () => {
        openView("graph");
        ai?.requestSuggestions(tableName);
    };

    const handleBack = async () => {
        await resetApp();
        onReset();
    };

    return (
        <div id="header">
            <AppTitle onReset={onReset} logoHeight="24" />
            <TableStatus />
            {/* Only offered while two nodes are paired: a shift-clicked selection A and the current node */}
            {comparisonPair && (
                <button
                    className="header-action-btn header-compare-btn"
                    onClick={() => openCompare(comparisonPair)}
                    title={`Compare ${comparisonPair.a} (selection A) with ${comparisonPair.b} (selection B)`}
                >
                    <img src="/images/icons/compare.svg" alt="" className="btn-svg-icon" />
                    Compare
                </button>
            )}
            <div className="navButtonContainer">
                {/* Each toggles its view; both can be open at once, side by side */}
                <NavButton
                    onClick={() => toggleView('graph')}
                    isSelected={openViews.includes('graph')}
                    icon={<img src="/images/icons/pgraphlogo.svg" alt="" className="navButtonSvgIcon" />}
                >
                    Provenance Graph
                </NavButton>
                <NavButton
                    onClick={() => toggleView('plots')}
                    isSelected={openViews.includes('plots')}
                    icon={<img src="/images/icons/plotlogo.svg" alt="" className="navButtonSvgIcon" />}
                >
                    {" Plots "}
                </NavButton>
            </div>
            <div className="headerActions">
                {/* Always here: opens the support-nodes window on the current node */}
                <button
                    className="header-action-btn"
                    onClick={() => openSupportWindow(tableName)}
                    title={`Add supporting nodes to ${nodeName(tableName)}`}
                >
                    <img src="/images/icons/support.svg" alt="" className="btn-svg-icon" />
                    Add Support Nodes
                </button>
                <button
                    className="header-action-btn"
                    onClick={askAI}
                    disabled={aiState.blocked}
                    title={aiState.detail}
                >
                    <img src="/images/icons/sparkle.svg" alt="" className="btn-svg-icon" />
                    AI Wrangle
                </button>
                <button
                    className="header-action-btn"
                    onClick={triggerRepairSelection}
                    disabled={busy || !hasSelection || repairLocked}
                    // Nothing is wrangled from a staged candidate until it is accepted
                    title={repairLocked ? `${CANDIDATE_LOCKED}.` : "Repair Selection"}
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
                <IconButton onClick={() => setSettingsOpen(true)} title="Settings" ariaLabel="Settings">&#9881;</IconButton>
                <IconButton onClick={handleBack} title="Home" ariaLabel="Home">&#8962;</IconButton>
            </div>
            <SettingsModal visible={settingsOpen} onClose={() => setSettingsOpen(false)} />
        </div>
    );
}
