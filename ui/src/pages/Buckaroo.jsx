import React, {createContext, useState} from "react";
import AttributeSummaryPanel from "../panels/AttributeSummaryPanel.jsx";
import TablePanel from "../panels/TablePanel.jsx";
import MatrixView from "../panels/SelectionPanel.jsx";
import RepairPanel from "../panels/RepairPanel.jsx";

import "./Buckaroo.css";
import PGraph from "../visualizations/PGraph.jsx";
import { BuckarooHeader } from "../elements/Header.jsx";
export const ViewContext = createContext();

export default function Buckaroo({ onReset, uploadResponse }) {

    const [selectedAttributes, setSelectedAttributes] = useState([]);
    const [sortedAttributes, setSortedAttributes] = useState([]);

    const table_name = uploadResponse?.table_name || "unknown_table";

    const [activeView, setActiveView] = useState('plots');

    console.log("Buckaroo received uploadResponse:", uploadResponse);

    return (
        <>
            <ViewContext.Provider value={{activeView, setActiveView}}>
                <BuckarooHeader onReset={onReset} />
                <div className="matrix-and-dropdown-container">
                    <AttributeSummaryPanel table_name={table_name} selectedAttributes={selectedAttributes} setSelectedAttributes={setSelectedAttributes} setSortedAttributes={setSortedAttributes} />

                    <div className="main-view">
                        <div className="svg-and-toolbox">

                            {/*Plot view*/}
                            {activeView === 'plots' &&
                                <>
                                    <MatrixView table_name={table_name} selectedAttributes={selectedAttributes} />
                                    <RepairPanel table_name={table_name} selectedAttributes={selectedAttributes} />
                                </>
                                }
                            {/*Graph view*/}
                            {activeView === 'graph' && <PGraph/>}

                        </div>
                        <div style={{ display: activeView === "plots" ? "block" : "none" }}>
                            <TablePanel table_name={table_name} sortedAttributes={sortedAttributes} />
                        </div>
                    </div>


                    <div id="tooltip" className="tooltip"></div>

                </div>
            </ViewContext.Provider>

        </>
    );
}

