import { createContext, useCallback, useContext, useState } from "react";
import { analyzeNode as apiAnalyze, materializeProposal as apiMaterialize } from "../utils/llmClient.jsx";
import { getPGraph, setGraphToClickedNode } from "../utils/serverCalls.jsx";
import { usePgraph } from "./PGraphContext.jsx";
import { useTableName } from "./TableNameContext.jsx";
import { ViewContext } from "../pages/Buckaroo.jsx";

// Lifecycle states:
//   idle              — nothing happening
//   fetching-table    — backend pulling table summary
//   prompting         — backend calling Ollama
//   proposals-ready   — shadow nodes rendered, awaiting user decision
//   materializing     — user accepted a shadow; backend running the wrangle
//   error             — last action failed; message in lastError
const STATUS = {
    IDLE: "idle",
    FETCHING: "fetching-table",
    PROMPTING: "prompting",
    READY: "proposals-ready",
    MATERIALIZING: "materializing",
    ERROR: "error",
};

const LLMOrchestratorContext = createContext(null);

const shadowId = (parentId, idx) => `shadow_${parentId}_${idx}`;

const MANUAL_WRANGLE_PROPOSAL = {
    op: "manual-wrangle",
    params: {},
    rationale: "Open the plots + repair panel and wrangle manually",
    predicted_table_name: "manual",
};

export function LLMOrchestratorProvider({ children }) {
    const { nodes, edges, setNodes, setEdges, getLayoutedElements } = usePgraph();
    const { setTableName } = useTableName();
    const viewContext = useContext(ViewContext);

    const [selectedNodeId, setSelectedNodeId] = useState(null);
    const [status, setStatus] = useState(STATUS.IDLE);
    const [lastError, setLastError] = useState(null);
    // proposals: array of { id, op, params, rationale, predicted_table_name }
    const [proposals, setProposals] = useState([]);

    const selectNode = useCallback((nodeId) => {
        setSelectedNodeId(nodeId);
    }, []);

    const clearShadows = useCallback(() => {
        setNodes((nds) => nds.filter((n) => !n.data?.isShadow));
        setEdges((eds) => eds.filter((e) => !e.data?.isShadow));
        setProposals([]);
    }, [setNodes, setEdges]);

    const renderShadows = useCallback((parentNodeId, props) => {
        const realNodes = nodes.filter((n) => !n.data?.isShadow);
        const realEdges = edges.filter((e) => !e.data?.isShadow);
        const shadows = props.map((p, i) => ({
            id: shadowId(parentNodeId, i),
            type: "shadowNode",
            position: { x: 0, y: 0 },
            data: {
                label: p.predicted_table_name || `proposal ${i + 1}`,
                isShadow: true,
                proposal: p,
                parentNodeId,
            },
        }));
        const shadowEdges = shadows.map((s) => ({
            id: `e_${parentNodeId}_${s.id}`,
            source: parentNodeId,
            target: s.id,
            type: "step",
            animated: true,
            style: { strokeDasharray: "4 4", opacity: 0.7 },
            data: { isShadow: true },
        }));
        // Pass the combined edges so dagre lays out shadows under their parent.
        const { nodes: laid, edges: laidEdges } = getLayoutedElements(
            [...realNodes, ...shadows],
            [...realEdges, ...shadowEdges],
        );
        setNodes(laid);
        setEdges(laidEdges);
    }, [nodes, edges, setNodes, setEdges, getLayoutedElements]);

    const startAnalysis = useCallback(async (nodeId) => {
        setSelectedNodeId(nodeId);
        setLastError(null);
        clearShadows();
        try {
            setStatus(STATUS.FETCHING);
            // backend handles the table-summary fetch + prompt round-trip; UI just toggles to prompting once it's in flight
            setStatus(STATUS.PROMPTING);
            const { proposals: props } = await apiAnalyze(nodeId);
            const withManual = [...(props || []), MANUAL_WRANGLE_PROPOSAL];
            setProposals(withManual);
            renderShadows(nodeId, withManual);
            setStatus(STATUS.READY);
        } catch (e) {
            setLastError(String(e));
            setStatus(STATUS.ERROR);
        }
    }, [clearShadows, renderShadows]);

    const acceptShadow = useCallback(async (shadowNodeId) => {
        const proposal = proposals.find((p, i) => shadowId(selectedNodeId, i) === shadowNodeId);
        if (!proposal) return;
        // Manual wrangle: skip the LLM/wrangler pipeline, just switch the user
        // into the plots+repair view on the selected node.
        if (proposal.op === "manual-wrangle") {
            try {
                await setGraphToClickedNode(selectedNodeId);
                setTableName(selectedNodeId);
                viewContext?.setActiveView?.("both");
                clearShadows();
                setStatus(STATUS.IDLE);
            } catch (e) {
                setLastError(String(e));
                setStatus(STATUS.ERROR);
            }
            return;
        }
        try {
            setStatus(STATUS.MATERIALIZING);
            const result = await apiMaterialize(selectedNodeId, proposal);
            // Refresh the pgraph from the backend so the new real node replaces the shadow.
            const pg = await getPGraph();
            if (pg?.nodes) {
                const { nodes: laid, edges: laidEdges } = getLayoutedElements(pg.nodes, pg.edges || []);
                setNodes(laid);
                setEdges(laidEdges);
            }
            if (result?.table) setTableName(result.table);
            setProposals([]);
            setStatus(STATUS.IDLE);
            return result?.table;
        } catch (e) {
            setLastError(String(e));
            setStatus(STATUS.ERROR);
        }
    }, [proposals, selectedNodeId, getLayoutedElements, setNodes, setEdges, setTableName, viewContext, clearShadows]);

    const rejectShadow = useCallback((shadowNodeId) => {
        const remainingNodes = nodes.filter((n) => n.id !== shadowNodeId);
        const remainingEdges = edges.filter((e) => e.target !== shadowNodeId);
        const { nodes: laid, edges: laidEdges } = getLayoutedElements(remainingNodes, remainingEdges);
        setNodes(laid);
        setEdges(laidEdges);
        setProposals((ps) => {
            const next = ps.filter((_, i) => shadowId(selectedNodeId, i) !== shadowNodeId);
            // When the last shadow is dismissed, exit the workflow.
            if (next.length === 0) {
                setStatus(STATUS.IDLE);
                setSelectedNodeId(null);
            }
            return next;
        });
    }, [nodes, edges, getLayoutedElements, setNodes, setEdges, selectedNodeId]);

    return (
        <LLMOrchestratorContext.Provider value={{
            selectedNodeId, selectNode,
            status, lastError,
            proposals,
            startAnalysis, acceptShadow, rejectShadow, clearShadows,
        }}>
            {children}
        </LLMOrchestratorContext.Provider>
    );
}

export function useLLMOrchestrator() {
    return useContext(LLMOrchestratorContext);
}
