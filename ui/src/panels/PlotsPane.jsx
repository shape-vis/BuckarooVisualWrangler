import MatrixView from "./SelectionPanel.jsx";
import PlotsWindow from "../elements/PlotsWindow.jsx";
import { ATTRIBUTES_TAB, usePlotsWindows } from "../store/plotsWindows.js";
import { useTableName } from "../store/TableNameContext.jsx";
import { nodeName } from "../utils/comparison.js";

import "../styles/PlotsPane.css";

/**
 * The Plots view: its windows as tabs, the way an editor stacks open files. The attribute plot matrix is always
 * the first; the compare and support-nodes windows join it while they are open and docked - see
 * PlotsWindowsContext.
 *
 * Every tab stays mounted whichever is showing, so switching away keeps the matrix's plots and each window's.
 * A docked window's pane is only a slot: its window moves its content into it, and out again when popped out, so
 * the content itself never remounts here.
 */
export default function PlotsPane({ selectedAttributes, plotFocus, onPlotFocused }) {
    const { activeTab, setActiveTab, docked } = usePlotsWindows();
    const { tableName } = useTableName();

    // A tab whose window has since closed or popped out falls back to the attribute plots
    const dockedIds = docked.map((entry) => entry.id);
    let tab = ATTRIBUTES_TAB;
    if (dockedIds.includes(activeTab)) {
        tab = activeTab;
    }

    const tabs = [{ id: ATTRIBUTES_TAB, label: "Attributes" }, ...docked];

    const attributeCount = selectedAttributes?.length ?? 0;
    const attributesNote = attributeCount === 0
        ? "Select attributes in the attribute panel to plot them"
        : "Brush or click a plot to select rows, then Repair";

    return (
        <div className="plots-pane">
            <div className="plots-pane-tabstrip" role="tablist">
                {tabs.map(({ id, label }) => (
                    <button
                        key={id}
                        type="button"
                        role="tab"
                        aria-selected={tab === id}
                        className={`plots-pane-tab ${tab === id ? "plots-pane-tab--active" : ""}`}
                        onClick={() => setActiveTab(id)}
                    >
                        {label}
                    </button>
                ))}
            </div>
            <div className="plots-pane-body" hidden={tab !== ATTRIBUTES_TAB}>
                <PlotsWindow
                    title={`Attribute plots · ${nodeName(tableName)}`}
                    titleId="attributes-title"
                    subtitle={attributesNote}
                >
                    <div className="plots-pane-matrix">
                        <MatrixView selectedAttributes={selectedAttributes} plotFocus={plotFocus} onPlotFocused={onPlotFocused} />
                    </div>
                </PlotsWindow>
            </div>
            {docked.map((entry) => (
                <div key={entry.id} className="plots-pane-body" ref={entry.dockSlot} hidden={tab !== entry.id} />
            ))}
        </div>
    );
}
