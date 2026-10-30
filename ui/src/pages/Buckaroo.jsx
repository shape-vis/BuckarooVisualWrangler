// Buckaroo.jsx
import { useState, useCallback, useEffect, useRef } from "react";
import { queryUploadStatus } from "../utils/serverCalls.jsx";
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
import AITutorial from "../elements/AITutorial.jsx";
import SelectionStatusBar from "../elements/SelectionStatusBar.jsx";
import DebugContextBridge from "../elements/DebugContextBridge.jsx";
import { RepairProvider } from "../store/RepairContext.jsx";
import {PGraphProvider} from "../store/PGraphContext.jsx";
import { ViewContext } from "../store/ViewContext.jsx";

function readPendingUpload() {
    const stored = sessionStorage.getItem("uploadResponse");
    if (!stored) return null;

    try {
        const uploadResponse = JSON.parse(stored);
        return uploadResponse?.loading_complete === false && uploadResponse?.table_name
            ? uploadResponse
            : null;
    } catch {
        return null;
    }
}

export default function Buckaroo({ onReset }) {
    const [selectedAttributes, setSelectedAttributes] = useState([]);
    const [sortedAttributes, setSortedAttributes] = useState([]);
    const [refreshKey, setRefreshKey] = useState(0);
    const [plotFocus, setPlotFocus] = useState({ scope: "", focused: false });
    const [pendingUpload] = useState(readPendingUpload);
    const [backgroundLoading, setBackgroundLoading] = useState(Boolean(pendingUpload));
    const [showTutorialSignal, setShowTutorialSignal] = useState(0);
    const pollTimerRef = useRef(null);

    const [activeView, setActiveView] = useState("plots");

    const handleWrangleExecuted = useCallback(() => {
        clearScatterPlotCache();
        clearHeatMapCache();
        clearHistogramCache();
        setRefreshKey(k => k + 1);
    }, []);

    const plotFocusScope = `${activeView}|${selectedAttributes.join("|")}`;
    const isPlotFocused = plotFocus.scope === plotFocusScope && plotFocus.focused;
    const handlePlotFocusChange = useCallback((focused) => {
        setPlotFocus({ scope: plotFocusScope, focused });
    }, [plotFocusScope]);

    useEffect(() => {
        const uploadResponse = pendingUpload;
        if (!uploadResponse) return undefined;
        const tableName = uploadResponse.table_name;

        const pollStatus = async () => {
            const status = await queryUploadStatus(tableName);
            if (status?.status === "complete") {
                setBackgroundLoading(false);
                sessionStorage.setItem(
                    "uploadResponse",
                    JSON.stringify({ ...uploadResponse, loading_complete: true }),
                );
                setRefreshKey((k) => k + 1);
                if (pollTimerRef.current) {
                    clearInterval(pollTimerRef.current);
                    pollTimerRef.current = null;
                }
            } else if (status?.status === "failed") {
                setBackgroundLoading(false);
                console.error("[Buckaroo] background detection failed:", status.error);
                if (pollTimerRef.current) {
                    clearInterval(pollTimerRef.current);
                    pollTimerRef.current = null;
                }
            }
        };

        pollStatus();
        pollTimerRef.current = setInterval(pollStatus, 2000);

        return () => {
            if (pollTimerRef.current) {
                clearInterval(pollTimerRef.current);
                pollTimerRef.current = null;
            }
        };
    }, [pendingUpload]);

    return (
        <>
            <ViewContext.Provider value={{ activeView, setActiveView, refreshKey, setRefreshKey}}>
                <SettingsProvider>
                <PGraphProvider>
                <RowRangeProvider>
                <SelectionProvider>
                <RepairProvider onWrangleExecuted={handleWrangleExecuted}>
                    <BuckarooHeader
                        onReset={onReset}
                        onShowAiGuide={() => setShowTutorialSignal(signal => signal + 1)}
                    />
                    <SelectionStatusBar />
                    <DebugContextBridge />
                    {backgroundLoading && (
                        <div className="background-loading-banner">
                            Analyzing full dataset in the background. Initial view uses the first 10,000 rows.
                        </div>
                    )}
                    <div key={refreshKey} className="matrix-and-dropdown-container">
                        <AttributeSummaryPanel
                            selectedAttributes={selectedAttributes}
                            setSelectedAttributes={setSelectedAttributes}
                            setSortedAttributes={setSortedAttributes}
                            refreshKey={refreshKey}
                        />

                        <div className="main-view">
                            <div className="svg-and-toolbox" data-tutorial-target="plots">

                                {/*Plot view*/}
                                {activeView === "plots" && (
                                    <>
                                        <MatrixView
                                            selectedAttributes={selectedAttributes}
                                            onFocusChange={handlePlotFocusChange}
                                            />
                                        <RepairPanel />
                                    </>
                                )}

                                {/*Graph View*/}
                                {activeView === "graph" &&
                                    <PGraph />}
                            </div>
                            <div className={`table-panel-wrapper ${activeView === "plots" && !isPlotFocused ? "table-panel-wrapper--visible" : ""}`}>
                                <TablePanel
                                    sortedAttributes={sortedAttributes}
                                />
                            </div>
                        </div>

                        <AITutorial
                            showSignal={showTutorialSignal}
                            selectedAttributes={selectedAttributes}
                        />

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
