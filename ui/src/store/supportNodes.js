import {useCallback, useMemo, useState} from "react";
import {supportId} from "../utils/graphTopology.js";
import {anchorOf, getSupportType} from "../graph_objects/supportNodes/registry.js";

/**
 * The supporting sub-nodes the user has hung beside nodes, and the modal that adds them.
 *
 * Called by PGraphProvider, whose graph-drawing effect is the only thing that writes what React Flow
 * draws, and spread into its context - so it is state of the graph view without growing the provider.
 *
 * Each sub-node is a plain JSON record, {id, hostId, kind, side, config, createdAt}, and every change
 * goes through the functions below. Nothing is saved yet: the records last as long as the page. Saving
 * them belongs here - load the records into this state when the graph loads, and write them on change -
 * and needs no change to how they are drawn.
 *
 * A record outlives its host disappearing from view - folded into a run, or undone - and is simply not
 * drawn meanwhile, so expanding or redoing brings it back.
 *
 * What is hidden is kept apart from the records: it is how the user is looking at them, not part of them,
 * so hiding never touches what would be saved. A host's own eye hides all of its sub-nodes - beside it and
 * beside its incoming edge; the graph's two toggles hide every side sub-node, or every edge sub-node, at once.
 */
export function useSupportNodes() {
    const [supportNodes, setSupportNodes] = useState([]);
    const [supportModalHost, setSupportModalHost] = useState(null);
    // Host ids whose sub-nodes are hidden by the host's own eye
    const [hiddenSupportHosts, setHiddenSupportHosts] = useState(() => new Set());
    // The graph-wide toggles, one per anchor
    const [hideAllNodeSupports, setHideAllNodeSupports] = useState(false);
    const [hideAllEdgeSupports, setHideAllEdgeSupports] = useState(false);

    // How many sub-nodes each host has of each anchor, {side, edge}, for the host's own controls
    const supportCountByHost = useMemo(() => {
        const counts = new Map();
        supportNodes.forEach((record) => {
            if (!counts.has(record.hostId)) counts.set(record.hostId, {side: 0, edge: 0});
            counts.get(record.hostId)[anchorOf(record)] += 1;
        });
        return counts;
    }, [supportNodes]);

    // How many there are of each anchor, for the graph-wide toggles
    const supportCountByAnchor = useMemo(() => {
        const counts = {side: 0, edge: 0};
        supportNodes.forEach((record) => { counts[anchorOf(record)] += 1; });
        return counts;
    }, [supportNodes]);

    /* Whether a record is drawn, as far as hiding goes - its host being drawn is the graph's business. A new
       function whenever what is hidden changes, so the graph's draw, which depends on it, runs again. */
    const isSupportShown = useCallback((record) => !hiddenSupportHosts.has(record.hostId)
        && (anchorOf(record) === "edge" ? !hideAllEdgeSupports : !hideAllNodeSupports),
    [hideAllEdgeSupports, hideAllNodeSupports, hiddenSupportHosts]);

    const setSupportHidden = useCallback((hostId, hidden) => {
        setHiddenSupportHosts((current) => {
            if (current.has(hostId) === hidden) return current;
            const next = new Set(current);
            if (hidden) next.add(hostId); else next.delete(hostId);
            return next;
        });
    }, []);

    const toggleSupportHidden = useCallback((hostId) => {
        setHiddenSupportHosts((current) => {
            const next = new Set(current);
            if (next.has(hostId)) next.delete(hostId); else next.add(hostId);
            return next;
        });
    }, []);

    // Returns the new sub-node's id, so whatever added it can find it again
    const addSupportNode = useCallback((hostId, kind, config) => {
        const key = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
        const id = supportId(hostId, key);
        // Adding where sub-nodes are hidden shows them, or the new one would seem to vanish
        if (getSupportType(kind)?.anchor === "edge") setHideAllEdgeSupports(false);
        else setHideAllNodeSupports(false);
        setSupportHidden(hostId, false);
        setSupportNodes((current) => {
            /* A kind that fixes its side keeps it; otherwise the layout puts it on the side its host's branch
               leans to, worked out each time the graph is drawn (supportLayout's branchSides) */
            const preferred = getSupportType(kind)?.side;
            const side = preferred === "left" || preferred === "right" ? preferred : "auto";

            return [...current, {
                id,
                hostId,
                kind,
                side,
                config,
                createdAt: new Date().toISOString(),
            }];
        });
        return id;
    }, [setSupportHidden]);

    // patch is merged into the record, or is a function of the record that returns what to merge
    const updateSupportNode = useCallback((id, patch) => {
        setSupportNodes((current) => current.map((record) => (record.id === id
            ? {...record, ...(typeof patch === "function" ? patch(record) : patch)}
            : record)));
    }, []);

    const removeSupportNode = useCallback((id) => {
        setSupportNodes((current) => current.filter((record) => record.id !== id));
    }, []);

    const openSupportModal = useCallback((hostId) => setSupportModalHost(hostId), []);
    const closeSupportModal = useCallback(() => setSupportModalHost(null), []);

    return {
        supportNodes, addSupportNode, updateSupportNode, removeSupportNode,
        supportModalHost, openSupportModal, closeSupportModal,
        supportCountByHost, hiddenSupportHosts, setSupportHidden, toggleSupportHidden,
        supportCountByAnchor, isSupportShown,
        hideAllNodeSupports, setHideAllNodeSupports, hideAllEdgeSupports, setHideAllEdgeSupports,
    };
}
