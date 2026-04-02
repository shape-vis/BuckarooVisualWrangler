// Buckaroo.jsx
import { createContext, useState } from "react";
import AttributeSummaryPanel from "../panels/AttributeSummaryPanel.jsx";
import TablePanel from "../panels/TablePanel.jsx";
import MatrixView from "../panels/SelectionPanel.jsx";
import RepairPanel from "../panels/RepairPanel.jsx";
import { SelectionProvider } from "../utils/SelectionContext.jsx";
import { RowRangeProvider } from "../utils/RowRangeContext.jsx";
import { SettingsProvider } from "../utils/SettingsContext.jsx";

import { clearScatterPlotCache, clearHeatMapCache, clearHistogramCache } from "../utils/visualizationCaches.jsx";
import "../styles/Buckaroo.css";
import PGraph from "../visualizations/PGraph.jsx";
import { BuckarooHeader } from "../elements/Header.jsx";

export const ViewContext = createContext();

export default function Buckaroo({ onReset }) {
    const [selectedAttributes, setSelectedAttributes] = useState([]);
    const [sortedAttributes, setSortedAttributes] = useState([]);
    const [refreshKey, setRefreshKey] = useState(0);

    const [activeView, setActiveView] = useState("plots");

    return (
        <>
            <ViewContext.Provider value={{ activeView, setActiveView }}>
                <SettingsProvider>
                <RowRangeProvider>
                {/* SelectionProvider wraps everything so both plots and RepairPanel share state */}
                <SelectionProvider>
                    <BuckarooHeader onReset={onReset} />
                    <div key={refreshKey} className="matrix-and-dropdown-container">
                        <AttributeSummaryPanel
                            selectedAttributes={selectedAttributes}
                            setSelectedAttributes={setSelectedAttributes}
                            setSortedAttributes={setSortedAttributes}
                        />

                        <div className="main-view">
                            <div className="svg-and-toolbox">
                                {/*Plot view*/}
                                {activeView === "plots" && (
                                    <>
                                        <MatrixView
                                            selectedAttributes={selectedAttributes}
                                        />
                                        <RepairPanel
                                            onWrangleExecuted={() => {
                                            clearScatterPlotCache();
                                            clearHeatMapCache();
                                            clearHistogramCache();
                                            setRefreshKey(k => k + 1);
                                        }}
                                        />
                                    </>
                                )}
                                {/*Graph View*/}
                                {activeView === "graph" &&
                                    <PGraph />}
                            </div>
                            <div className={`table-panel-wrapper ${activeView === "plots" ? "table-panel-wrapper--visible" : ""}`}>
                                <TablePanel
                                    sortedAttributes={sortedAttributes}
                                />
                            </div>
                        </div>

                        <div id="tooltip" className="tooltip"></div>
                    </div>
                </SelectionProvider>
                </RowRangeProvider>
                </SettingsProvider>
            </ViewContext.Provider>
        </>
    );
}
