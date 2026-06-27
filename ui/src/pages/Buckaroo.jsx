// Buckaroo.jsx
import { createContext, useState, useCallback, useEffect, useRef } from "react";
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

export const ViewContext = createContext();



export default function Buckaroo({ onReset }) {
    const [selectedAttributes, setSelectedAttributes] = useState([]);
    const [sortedAttributes, setSortedAttributes] = useState([]);
    const [refreshKey, setRefreshKey] = useState(0);
    const [isPlotFocused, setIsPlotFocused] = useState(false);
    const [backgroundLoading, setBackgroundLoading] = useState(false);
    const [showTutorialSignal, setShowTutorialSignal] = useState(0);
    const pollTimerRef = useRef(null);

    const [activeView, setActiveView] = useState("plots");

    const handleWrangleExecuted = useCallback(() => {
        clearScatterPlotCache();
        clearHeatMapCache();
        clearHistogramCache();
        setRefreshKey(k => k + 1);
    }, []);

    useEffect(() => {
        setIsPlotFocused(false);
    }, [activeView, selectedAttributes]);

    useEffect(() => {
        const stored = sessionStorage.getItem("uploadResponse");
        if (!stored) return undefined;

        let uploadResponse;
        try {
            uploadResponse = JSON.parse(stored);
        } catch {
            return undefined;
        }

        if (uploadResponse?.loading_complete !== false || !uploadResponse?.table_name) {
            setBackgroundLoading(false);
            return undefined;
        }

        setBackgroundLoading(true);
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
    }, []);

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
                    <AITutorial showSignal={showTutorialSignal} />
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
                                            onFocusChange={setIsPlotFocused}
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
