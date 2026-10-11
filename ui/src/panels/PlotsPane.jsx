import MatrixView from "./SelectionPanel.jsx";
import { useCompare } from "../store/CompareContext.jsx";

import "../styles/PlotsPane.css";

/**
 * The Plots view: the attribute plot matrix and, while a comparison is docked, the compare panel as a second
 * tab - the way RightDock stacks its panels.
 *
 * Both stay mounted whichever tab is showing, so switching away keeps the matrix's plots and the panel's.
 * The Compare tab's pane is only a slot: CompareContext moves the panel into it, and out again when the
 * panel is popped out, so the panel itself never remounts here. Without a docked comparison there is no
 * tab strip, and the view looks as it always has.
 */

const TABS = [
    { id: "attributes", label: "Attributes" },
    { id: "compare", label: "Compare" },
];

export default function PlotsPane({ selectedAttributes }) {
    const { spec, placement, plotsTab, setPlotsTab, dockSlot } = useCompare();
    const docked = Boolean(spec) && placement === "docked";
    const tab = docked ? plotsTab : "attributes";

    return (
        <div className="plots-pane">
            {docked && (
                <div className="plots-pane-tabstrip" role="tablist">
                    {TABS.map(({ id, label }) => (
                        <button
                            key={id}
                            type="button"
                            role="tab"
                            aria-selected={tab === id}
                            className={`plots-pane-tab ${tab === id ? "plots-pane-tab--active" : ""}`}
                            onClick={() => setPlotsTab(id)}
                        >
                            {label}
                        </button>
                    ))}
                </div>
            )}
            <div className="plots-pane-body" hidden={tab !== "attributes"}>
                <MatrixView selectedAttributes={selectedAttributes} />
            </div>
            <div className="plots-pane-body" ref={dockSlot} hidden={tab !== "compare"} />
        </div>
    );
}
