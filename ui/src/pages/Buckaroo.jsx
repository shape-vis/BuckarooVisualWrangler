// Buckaroo.jsx
import { createContext, useState } from "react";
import AttributeSummaryPanel from "../panels/AttributeSummaryPanel.jsx";
import TablePanel from "../panels/TablePanel.jsx";
import MatrixView from "../panels/SelectionPanel.jsx";
import RepairPanel from "../panels/RepairPanel.jsx";
import { SelectionProvider } from "../utils/SelectionContext.jsx";
import { RowRangeProvider } from "../utils/RowRangeContext.jsx";

import "./Buckaroo.css";
import PGraph from "../visualizations/PGraph.jsx";
import { BuckarooHeader } from "../elements/Header.jsx";

export const ViewContext = createContext();

export default function Buckaroo({ onReset, uploadResponse }) {
    const [selectedAttributes, setSelectedAttributes] = useState([]);
    const [sortedAttributes, setSortedAttributes] = useState([]);

    const table_name = uploadResponse?.table_name || "unknown_table";
    const [activeView, setActiveView] = useState("plots");

    return (
        <>
            <ViewContext.Provider value={{ activeView, setActiveView }}>
                <RowRangeProvider>
                {/* SelectionProvider wraps everything so both plots and RepairPanel share state */}
                <SelectionProvider>
                    <BuckarooHeader onReset={onReset} />
                    <div className="matrix-and-dropdown-container">
                        <AttributeSummaryPanel
                            table_name={table_name}
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
                                            table_name={table_name}
                                            selectedAttributes={selectedAttributes}
                                        />
                                        <RepairPanel table_name={table_name} />
                                    </>
                                )}
                                {/*Graph View*/}
                                {activeView === "graph" && <PGraph />}
                            </div>
                            <div style={{ display: activeView === "plots" ? "block" : "none" }}>
                                <TablePanel
                                    table_name={table_name}
                                    sortedAttributes={sortedAttributes}
                                />
                            </div>
                        </div>

                        <div id="tooltip" className="tooltip"></div>
                    </div>
                </SelectionProvider>
                </RowRangeProvider>
            </ViewContext.Provider>
        </>
    );
}
