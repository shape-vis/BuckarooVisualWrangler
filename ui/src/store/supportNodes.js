import {useCallback, useMemo, useState} from "react";
import {supportId} from "../utils/graphTopology.js";
import {randomKey} from "../utils/randomKey.js";
import {anchorOf, getSupportType} from "../graph_objects/supportNodes/registry.js";

// The drag data type a sub-node dragged in from outside the graph carries - a Quality panel card sets it
export const SUPPORT_DRAG_TYPE = "application/x-buckaroo-support";

/* The side a new sub-node of this kind goes on: the one its kind fixes, if it fixes one. Otherwise "auto", and
   the layout puts it on the side its host's branch leans to, worked out each time the graph is drawn
   (supportLayout's branchSides). */
function initialSide(supportType) {
    const preferred = supportType?.side;
    if (preferred === "left" || preferred === "right") return preferred;
    return "auto";
}

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
    /* A sub-node being dragged in from outside the graph - a Quality panel sparkline - or null. While it is set
       the graph draws a drop zone over its host's group (see SupportDropZone), and dropping there adds it:
       {hostId, kind, config}. */
    const [supportDrag, setSupportDrag] = useState(null);

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
    const isSupportShown = useCallback((record) => {
        const hiddenByHost = hiddenSupportHosts.has(record.hostId);
        if (hiddenByHost) return false;

        const besideEdge = anchorOf(record) === "edge";
        if (besideEdge) return !hideAllEdgeSupports;
        return !hideAllNodeSupports;
    }, [hideAllEdgeSupports, hideAllNodeSupports, hiddenSupportHosts]);

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
        const id = supportId(hostId, randomKey());
        const supportType = getSupportType(kind);

        // Adding where sub-nodes are hidden shows them, or the new one would seem to vanish
        if (supportType?.anchor === "edge") setHideAllEdgeSupports(false);
        else setHideAllNodeSupports(false);
        setSupportHidden(hostId, false);

        const record = {
            id,
            hostId,
            kind,
            side: initialSide(supportType),
            config,
            createdAt: new Date().toISOString(),
        };
        setSupportNodes((current) => [...current, record]);
        return id;
    }, [setSupportHidden]);

    // patch is merged into the record, or is a function of the record that returns what to merge
    const updateSupportNode = useCallback((id, patch) => {
        setSupportNodes((current) => current.map((record) => {
            if (record.id !== id) return record;

            let changes = patch;
            if (typeof patch === "function") changes = patch(record);
            return {...record, ...changes};
        }));
    }, []);

    const removeSupportNode = useCallback((id) => {
        setSupportNodes((current) => current.filter((record) => record.id !== id));
    }, []);

    // Every sub-node of these hosts - for a candidate that is declined, whose node is gone with it
    const removeSupportNodesOf = useCallback((hostIds) => {
        const gone = new Set(hostIds);
        setSupportNodes((current) => current.filter((record) => !gone.has(record.hostId)));
    }, []);

    const openSupportModal = useCallback((hostId) => setSupportModalHost(hostId), []);
    const closeSupportModal = useCallback(() => setSupportModalHost(null), []);

    const startSupportDrag = useCallback((payload) => setSupportDrag(payload), []);
    const endSupportDrag = useCallback(() => setSupportDrag(null), []);

    return {
        supportNodes, addSupportNode, updateSupportNode, removeSupportNode, removeSupportNodesOf,
        supportModalHost, openSupportModal, closeSupportModal,
        supportCountByHost, hiddenSupportHosts, toggleSupportHidden,
        supportCountByAnchor, isSupportShown,
        hideAllNodeSupports, setHideAllNodeSupports, hideAllEdgeSupports, setHideAllEdgeSupports,
        supportDrag, startSupportDrag, endSupportDrag,
    };
}
