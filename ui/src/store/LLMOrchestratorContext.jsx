import { createContext, useCallback, useContext, useState } from "react";
import {
    analyzeNode as apiAnalyze,
    materializeProposal as apiMaterialize,
    previewProposal as apiPreview,
    materializePlan as apiMaterializePlan,
    previewPlan as apiPreviewPlan,
} from "../utils/llmClient.jsx";
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
    kind: "manual",
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
    // activePreview: { shadowId, previewTable, column, deltas } | null
    const [activePreview, setActivePreview] = useState(null);
    const [previewLoading, setPreviewLoading] = useState(false);

    const selectNode = useCallback((nodeId) => {
        setSelectedNodeId(nodeId);
    }, []);

    const clearShadows = useCallback(() => {
        setNodes((nds) => nds.filter((n) => !n.data?.isShadow && n.type !== "planStepShadow"));
        setEdges((eds) => eds.filter((e) => !e.data?.isShadow && !e.id?.startsWith("step_e_")));
        setProposals([]);
        setActivePreview(null);
    }, [setNodes, setEdges]);

    const renderShadows = useCallback((parentNodeId, props) => {
        const realNodes = nodes.filter((n) => !n.data?.isShadow);
        const realEdges = edges.filter((e) => !e.data?.isShadow);
        const shadows = props.map((p, i) => {
            const label = p.kind === "plan"
                ? (p.name || `Plan ${i + 1}`)
                : (p.predicted_table_name || `proposal ${i + 1}`);
            return {
                id: shadowId(parentNodeId, i),
                type: p.kind === "plan" ? "planShadowNode" : "shadowNode",
                position: { x: 0, y: 0 },
                data: {
                    label,
                    isShadow: true,
                    proposal: p,
                    parentNodeId,
                },
            };
        });
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
            const resp = await apiAnalyze(nodeId);
            const singles = (resp.proposals || []).map((p) => ({ ...p, kind: "single" }));
            const planEntries = (resp.plans || []).map((p) => ({ ...p, kind: "plan" }));
            const all = [...singles, ...planEntries, MANUAL_WRANGLE_PROPOSAL];
            setProposals(all);
            renderShadows(nodeId, all);
            setStatus(STATUS.READY);
        } catch (e) {
            setLastError(String(e));
            setStatus(STATUS.ERROR);
        }
    }, [clearShadows, renderShadows]);

    const acceptShadow = useCallback(async (shadowNodeId) => {
        const proposal = proposals.find((p, i) => shadowId(selectedNodeId, i) === shadowNodeId);
        if (!proposal) return;

        // Multi-step plan: sequential materialize on the backend.
        if (proposal.kind === "plan") {
            try {
                setStatus(STATUS.MATERIALIZING);
                const result = await apiMaterializePlan(selectedNodeId, proposal);
                const pg = await getPGraph();
                if (pg?.nodes) {
                    const { nodes: laid, edges: laidEdges } = getLayoutedElements(pg.nodes, pg.edges || []);
                    setNodes(laid);
                    setEdges(laidEdges);
                }
                if (result?.final_table) setTableName(result.final_table);
                setProposals([]);
                setActivePreview(null);
                setStatus(STATUS.IDLE);
                if (result?.error) setLastError(`Plan stopped at step ${result.stopped_at}: ${result.error}`);
                return result?.final_table;
            } catch (e) {
                console.error("[acceptShadow plan]", e);
                setLastError(String(e));
                setStatus(STATUS.ERROR);
            }
            return;
        }

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

    const removeStepShadows = useCallback(() => {
        setNodes((nds) => nds.filter((n) => n.type !== "planStepShadow"));
        setEdges((eds) => eds.filter((e) => !e.id?.startsWith("step_e_")));
    }, [setNodes, setEdges]);

    const renderStepShadows = useCallback((parentShadowId, steps) => {
        const stepNodes = steps.map((s, i) => ({
            id: `step_${parentShadowId}_${i}`,
            type: "planStepShadow",
            position: { x: 0, y: 0 },
            data: {
                label: `Step ${i + 1}${s.name ? `: ${s.name}` : ""}`,
                isShadow: true,
                step: s,
            },
        }));
        const stepEdges = stepNodes.map((n, i) => ({
            id: `step_e_${parentShadowId}_${i}`,
            source: i === 0 ? parentShadowId : stepNodes[i - 1].id,
            target: n.id,
            type: "step",
            animated: true,
            style: { strokeDasharray: "4 4", opacity: 0.7 },
            data: { isShadow: true },
        }));
        const realNodes = nodes.filter((n) => n.type !== "planStepShadow");
        const realEdges = edges.filter((e) => !e.id?.startsWith("step_e_"));
        const { nodes: laid, edges: laidEdges } = getLayoutedElements(
            [...realNodes, ...stepNodes],
            [...realEdges, ...stepEdges],
        );
        setNodes(laid);
        setEdges(laidEdges);
    }, [nodes, edges, setNodes, setEdges, getLayoutedElements]);

    const requestPreview = useCallback(async (shadowNodeId) => {
        const idx = proposals.findIndex((_, i) => shadowId(selectedNodeId, i) === shadowNodeId);
        const proposal = idx >= 0 ? proposals[idx] : null;
        if (!proposal || proposal.op === "manual-wrangle") return;
        // Toggling off the currently-previewed shadow
        if (activePreview?.shadowId === shadowNodeId) {
            setActivePreview(null);
            removeStepShadows();
            return;
        }
        // Switching to a new preview — clear any previous step shadows first
        removeStepShadows();
        try {
            setPreviewLoading(true);
            if (proposal.kind === "plan") {
                const res = await apiPreviewPlan(selectedNodeId, proposal);
                setActivePreview({
                    shadowId: shadowNodeId,
                    kind: "plan",
                    steps: res.steps,
                });
                renderStepShadows(shadowNodeId, res.steps || []);
            } else {
                const res = await apiPreview(selectedNodeId, proposal);
                setActivePreview({
                    shadowId: shadowNodeId,
                    kind: "single",
                    previewTable: res.preview_table,
                    column: res.affected_column,
                    deltas: res.deltas,
                });
            }
        } catch (e) {
            console.error("[requestPreview]", e);
            setLastError(String(e));
        } finally {
            setPreviewLoading(false);
        }
    }, [proposals, selectedNodeId, activePreview, removeStepShadows, renderStepShadows]);

    const rejectShadow = useCallback((shadowNodeId) => {
        const remainingNodes = nodes.filter((n) => n.id !== shadowNodeId);
        const remainingEdges = edges.filter((e) => e.target !== shadowNodeId);
        const { nodes: laid, edges: laidEdges } = getLayoutedElements(remainingNodes, remainingEdges);
        setNodes(laid);
        setEdges(laidEdges);
        if (activePreview?.shadowId === shadowNodeId) setActivePreview(null);
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
            activePreview, previewLoading, requestPreview,
            startAnalysis, acceptShadow, rejectShadow, clearShadows,
        }}>
            {children}
        </LLMOrchestratorContext.Provider>
    );
}

export function useLLMOrchestrator() {
    return useContext(LLMOrchestratorContext);
}
