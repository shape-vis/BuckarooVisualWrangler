import React, { useState } from "react";
import AttributeSummaryPanel from "../panels/AttributeSummaryPanel.jsx";
import TablePanel from "../panels/TablePanel.jsx";

import Header from "../elements/Header.jsx";
import MatrixView from "../panels/SelectionPanel.jsx";
import RepairPanel from "../panels/RepairPanel.jsx";

import "./Buckaroo.css";


export default function Buckaroo({ onReset, uploadResponse }) {

    const [selectedAttributes, setSelectedAttributes] = useState([]);
    const [sortedAttributes, setSortedAttributes] = useState([]);

    const table_name = uploadResponse?.table_name || "unknown_table";

    console.log("Buckaroo received uploadResponse:", uploadResponse);

    return (
        <>
            <Header onReset={onReset} />

            <div className="matrix-and-dropdown-container">

                <AttributeSummaryPanel table_name={table_name} selectedAttributes={selectedAttributes} setSelectedAttributes={setSelectedAttributes} setSortedAttributes={setSortedAttributes} />

                <div className="main-view">
                    <div className="svg-and-toolbox">
                        <MatrixView table_name={table_name} selectedAttributes={selectedAttributes} />
                        <RepairPanel table_name={table_name} selectedAttributes={selectedAttributes} />
                    </div>
                    <TablePanel table_name={table_name} sortedAttributes={sortedAttributes} />
                </div>


                <div id="tooltip" className="tooltip"></div>

            </div>


        </>
    );
}

