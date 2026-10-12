// Buckaroo.jsx
import { createContext, useState, useCallback } from "react";
import AttributeSummaryPanel from "../panels/AttributeSummaryPanel.jsx";
import TablePanel from "../panels/TablePanel.jsx";
import PlotsPane from "../panels/PlotsPane.jsx";
import RightDock from "../panels/RightDock.jsx";
import { SelectionProvider } from "../store/SelectionContext.jsx";
import { RowRangeProvider } from "../store/RowRangeContext.jsx";
import { SettingsProvider } from "../store/SettingsContext.jsx";

import { clearScatterPlotCache, clearHeatMapCache, clearHistogramCache } from "../store/visualizationCaches.jsx";
import "../styles/Buckaroo.css";
import PGraph from "../visualizations/PGraph.jsx";
import { BuckarooHeader } from "../elements/Header.jsx";
import { RepairProvider } from "../store/RepairContext.jsx";
import {PGraphProvider} from "../store/PGraphContext.jsx";
import {AISuggestionsProvider} from "../store/AISuggestionsContext.jsx";
import {DockProvider} from "../store/DockContext.jsx";
import {CompareProvider} from "../store/CompareContext.jsx";
import SplitDivider, {DEFAULT_SPLIT} from "../elements/SplitDivider.jsx";

export const ViewContext = createContext();

const MAX_OPEN_VIEWS = 2;
// The attribute panel keeps at most this many attributes selected, dropping the oldest past it
const MAX_SELECTED_ATTRIBUTES = 3;

/* The selected attributes with columns added, oldest dropped past the cap - though never one of the columns
   being added, which are the point. */
function withAttributes(selected, columns) {
    const next = [...selected, ...columns.filter((column) => !selected.includes(column))];
    while (next.length > MAX_SELECTED_ATTRIBUTES) {
        const drop = next.findIndex((column) => !columns.includes(column));
        if (drop < 0) break;
        next.splice(drop, 1);
    }
    return next;
}



export default function Buckaroo({ onReset }) {
    const [selectedAttributes, setSelectedAttributes] = useState([]);
    const [sortedAttributes, setSortedAttributes] = useState([]);
    const [refreshKey, setRefreshKey] = useState(0);

    /* The views on screen, oldest first. Both can sit side by side, and the last open view cannot be
       closed, so the main area is never empty. MAX_OPEN_VIEWS keeps a later third view to two. */
    const [openViews, setOpenViews] = useState(["plots"]);

    const toggleView = useCallback((view) => {
        setOpenViews((current) => {
            if (current.includes(view)) {
                return current.length > 1 ? current.filter((open) => open !== view) : current;
            }
            return [...current, view].slice(-MAX_OPEN_VIEWS);
        });
    }, []);

    /* The Plots view's share of the width it splits with the graph. Held here, above the container a wrangle
       remounts, so a dragged divider stays where it was put. */
    const [split, setSplit] = useState(DEFAULT_SPLIT);

    // Opens a view if it is closed, and leaves it open if it is not - for a view asking to be shown
    const openView = useCallback((view) => {
        setOpenViews((current) => (current.includes(view) ? current : [...current, view].slice(-MAX_OPEN_VIEWS)));
    }, []);
    const revealPlots = useCallback(() => openView("plots"), [openView]);

    /* A plot the Plots view is asked to zoom to: its columns, x then y, stamped so asking for the same one twice
       still counts. The matrix applies it once its columns are among the selected attributes, then hands it back
       here to be dropped - only that request, should a newer one have arrived meanwhile. */
    const [plotFocus, setPlotFocus] = useState(null);
    const dropPlotFocus = useCallback((key) => {
        setPlotFocus((current) => (current?.key === key ? null : current));
    }, []);

    /** Shows one plot in the Plots view - where brushing and wrangling happen - selecting its columns if they
        are not already, and zoomed to it as its magnifier would. */
    const focusPlot = useCallback((columns) => {
        setSelectedAttributes((selected) => withAttributes(selected, columns));
        setPlotFocus({columns, key: Date.now()});
        openView("plots");
    }, [openView]);

    const handleWrangleExecuted = useCallback(() => {
        clearScatterPlotCache();
        clearHeatMapCache();
        clearHistogramCache();
        setRefreshKey(k => k + 1);
    }, []);

    return (
        <>
            {/* selectedAttributes too: the error-plot sub-node's gallery offers the same columns the Plots view shows */}
            <ViewContext.Provider value={{ openViews, toggleView, openView, refreshKey, setRefreshKey, selectedAttributes, focusPlot}}>
                <SettingsProvider>
                {/* Above PGraph and Repair: both ask the dock to show their tab */}
                <DockProvider>
                <PGraphProvider>
                {/* Inside PGraphProvider: the graph owns the suggestion nodes, this owns asking
                    for them. Accepting one runs the same post-wrangle sequence RepairContext does. */}
                <AISuggestionsProvider onWrangleExecuted={handleWrangleExecuted}>
                <RowRangeProvider>
                <SelectionProvider>
                <RepairProvider onWrangleExecuted={handleWrangleExecuted}>
                {/* Outside the keyed container below, so an open comparison survives a wrangle. It docks
                    into the Plots view, and opens that view to do so. */}
                <CompareProvider revealPlots={revealPlots}>
                    <BuckarooHeader onReset={onReset} />
                    <div key={refreshKey} className="matrix-and-dropdown-container">
                        <AttributeSummaryPanel
                            selectedAttributes={selectedAttributes}
                            setSelectedAttributes={setSelectedAttributes}
                            setSortedAttributes={setSortedAttributes}
                        />

                        <div className="main-view">
                            <div
                                className="svg-and-toolbox"
                                // Only while both share the row: a lone view's grow under 1 would leave it short of filling it
                                style={openViews.length > 1 ? {"--plots-grow": split, "--graph-grow": 1 - split} : undefined}
                            >

                                {/* Whichever views are open, always in this order, so the pair
                                    does not swap sides depending on which was opened first */}
                                {openViews.includes("plots") && (
                                    <PlotsPane
                                        selectedAttributes={selectedAttributes}
                                        plotFocus={plotFocus}
                                        onPlotFocused={dropPlotFocus}
                                    />
                                )}

                                {openViews.length > 1 && <SplitDivider split={split} onSplit={setSplit} />}

                                {openViews.includes("graph") && <PGraph />}

                                {/*Repair and node details, as tabs in one resizable dock*/}
                                <RightDock />
                            </div>
                            <div className={`table-panel-wrapper ${openViews.includes("plots") ? "table-panel-wrapper--visible" : ""}`}>
                                <TablePanel
                                    sortedAttributes={sortedAttributes}
                                />
                            </div>
                        </div>

                        <div id="tooltip" className="tooltip"></div>
                    </div>
                </CompareProvider>
                </RepairProvider>
                </SelectionProvider>
                </RowRangeProvider>
                </AISuggestionsProvider>
                </PGraphProvider>
                </DockProvider>
                </SettingsProvider>
            </ViewContext.Provider>
        </>
    );
}
