// Buckaroo.jsx
import { createContext, useState, useCallback } from "react";
import AttributeSummaryPanel from "../panels/AttributeSummaryPanel.jsx";
import TablePanel from "../panels/TablePanel.jsx";
import MatrixView from "../panels/SelectionPanel.jsx";
import RepairPanel from "../panels/RepairPanel.jsx";
import { SelectionProvider } from "../store/SelectionContext.jsx";
import { RowRangeProvider } from "../store/RowRangeContext.jsx";
import { SettingsProvider } from "../store/SettingsContext.jsx";

import { clearScatterPlotCache, clearHeatMapCache, clearHistogramCache } from "../store/visualizationCaches.jsx";
import "../styles/Buckaroo.css";
import PGraph from "../visualizations/PGraph.jsx";
import { BuckarooHeader } from "../elements/Header.jsx";
import { RepairProvider } from "../store/RepairContext.jsx";
import {PGraphProvider} from "../store/PGraphContext.jsx";

export const ViewContext = createContext();



export default function Buckaroo({ onReset }) {
    const [selectedAttributes, setSelectedAttributes] = useState([]);
    const [sortedAttributes, setSortedAttributes] = useState([]);
    const [refreshKey, setRefreshKey] = useState(0);

    const [activeView, setActiveView] = useState("both");

    const handleWrangleExecuted = useCallback(() => {
        clearScatterPlotCache();
        clearHeatMapCache();
        clearHistogramCache();
        setRefreshKey(k => k + 1);
    }, []);

    return (
        <>
            <ViewContext.Provider value={{ activeView, setActiveView, refreshKey, setRefreshKey}}>
                <SettingsProvider>
                <PGraphProvider>
                <RowRangeProvider>
                <SelectionProvider>
                <RepairProvider onWrangleExecuted={handleWrangleExecuted}>
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
                                        <RepairPanel />
                                    </>
                                )}

                                {/*Plots and Graph view*/}
                                {activeView === "both" && (
                                    <>
                                        <MatrixView
                                            selectedAttributes={selectedAttributes}
                                        />
                                        <PGraph />
                                        <RepairPanel />
                                    </>
                                )}

                                {/*Graph View*/}
                                {activeView === "graph" &&
                                    <PGraph />}
                            </div>
                            <div className={`table-panel-wrapper ${activeView === "both" || activeView === "plots" ? "table-panel-wrapper--visible" : ""}`}>
                                <TablePanel
                                    sortedAttributes={sortedAttributes}
                                />
                            </div>
                        </div>

                        <div id="tooltip" className="tooltip"></div>
                    </div>
                </RepairProvider>
                </SelectionProvider>
                </RowRangeProvider>
                </PGraphProvider>
                </SettingsProvider>
            </ViewContext.Provider>
        </>
    );
}
