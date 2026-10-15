import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import ComparePanel from "../elements/ComparePanel.jsx";
import { usePgraph } from "./PGraphContext.jsx";
import { HostWindowContext } from "./HostWindowContext.jsx";
import { usePlotsWindows, useDockableWindow } from "./plotsWindows.js";
import { normalizeSpec, specFromPair } from "../utils/comparisonSpec.js";
import { randomKey } from "../utils/randomKey.js";
import { savedCompareConfig, specOfCompare } from "../graph_objects/supportNodes/compareView.js";

/**
 * The open comparison. It is shown in one of the Plots view's windows - docked as a tab or popped out, which
 * useDockableWindow handles - so this keeps only what is being compared, and the compare sub-nodes it is kept on.
 *
 * Code inside the panel cannot assume it runs in this window: see HostWindowContext.jsx.
 */

const CompareContext = createContext(null);

const WINDOW_ID = "compare";
const WINDOW_LABEL = "Compare";

/* Whether the open comparison is this same pair, opened from the graph. One opened from a sub-node is kept
   apart: it is linked to that sub-node, which the graph's own pair is not. */
function isSamePairOpen(open, spec) {
    if (!open) return false;

    const openedFromGraph = !open.links;
    if (!openedFromGraph) return false;

    return open.spec.a === spec.a && open.spec.b === spec.b;
}

/* The compare sub-nodes that follow one comparison together: every one a single Save added, or just this one */
function compareGroupOf(record, supportNodes) {
    const group = record.config?.group;
    if (!group) return [record.id];

    const sameGroup = supportNodes.filter((one) => one.kind === record.kind && one.config?.group === group);
    return sameGroup.map((one) => one.id);
}

export function CompareProvider({ children }) {
    const { nodes, serverNodesById, supportNodes, addSupportNode, updateSupportNode } = usePgraph();
    const { showWindow } = usePlotsWindows();

    /* The open comparison and a serial for it, which keys the panel so each new one starts fresh. links are the
       compare sub-nodes it is kept on - see openCompareNode and saveToNodes. */
    const [open, setOpen] = useState(null);
    const serial = useRef(0);

    const forgetComparison = useCallback(() => setOpen(null), []);
    const dock = useDockableWindow({
        id: WINDOW_ID, label: WINDOW_LABEL, open: Boolean(open), onClose: forgetComparison,
    });

    const bringForward = useCallback(() => showWindow(WINDOW_ID), [showWindow]);

    /* follow says what the linked sub-nodes keep of the comparison as it changes: the whole of it (a compare
       sub-node), or only its column while it is on drift (a drift-plot sub-node, whose settings are its column). */
    const show = useCallback((spec, { links = null, follow = "spec" } = {}) => {
        serial.current += 1;
        setOpen({ spec, key: serial.current, links, follow });
        bringForward();
    }, [bringForward]);

    /** Compares the two nodes paired in the graph. The same pair again just brings the open one forward. */
    const openCompare = useCallback((pair) => {
        const nodesById = Object.fromEntries(nodes.map((node) => [node.id, node]));
        const spec = specFromPair(pair, nodesById);
        if (isSamePairOpen(open, spec)) {
            bringForward();
            return;
        }
        show(spec);
    }, [nodes, open, show, bringForward]);

    /** Opens a compare sub-node in the panel. Every sub-node one Save added changes along with it. The one
        already open is just brought forward. */
    const openCompareNode = useCallback((record) => {
        const alreadyOpen = open?.links?.includes(record.id);
        if (alreadyOpen) {
            bringForward();
            return;
        }
        const links = compareGroupOf(record, supportNodes);
        const columns = Object.keys(serverNodesById?.[record.hostId]?.data?.metrics?.columns ?? {});
        show(specOfCompare(record, columns), { links });
    }, [supportNodes, serverNodesById, open, show, bringForward]);

    /** Opens a drift-plot sub-node in the panel: its node against root - a single-node comparison - on drift, on
        its column. Picking another column there while on drift carries back to the sub-node. The one already open
        is just brought forward. */
    const openDriftNode = useCallback((record) => {
        const alreadyOpen = open?.links?.includes(record.id);
        if (alreadyOpen) {
            bringForward();
            return;
        }
        const spec = normalizeSpec({
            a: record.hostId,
            b: record.hostId,
            anchor: record.hostId,
            kind: "drift",
            x: record.config?.column ?? "",
            // One node has no other to measure against, only how far it has come from the upload
            errorDelta: "rootB",
        });
        show(spec, { links: [record.id], follow: "driftColumn" });
    }, [open, show, bringForward]);

    // While a comparison is kept on sub-nodes, they follow its settings - all of them, or just what they keep
    const links = open?.links;
    const follow = open?.follow;
    const followSpec = useCallback((spec) => {
        if (!links) return;

        // What one linked sub-node takes from the comparison's new settings
        function patchFor(record) {
            if (follow !== "driftColumn") {
                return { config: { ...record.config, spec } };
            }
            // A drift plot keeps only its column, and only while the comparison is on drift
            const onDriftColumn = spec.kind === "drift" && spec.x;
            if (onDriftColumn) {
                return { config: { ...record.config, column: spec.x } };
            }
            return {};
        }

        links.forEach((id) => updateSupportNode(id, patchFor));
    }, [links, follow, updateSupportNode]);

    /* Keeps the open comparison beside both its nodes, as a compare sub-node on each, and from then on they
       follow it. Grouped, so opening either later changes both. */
    const saveToNodes = useCallback((spec) => {
        const group = randomKey();
        // A single-node comparison has the one host
        const hosts = [...new Set([spec.a, spec.b])];
        const ids = hosts.map((host) => addSupportNode(host, "compare", savedCompareConfig(spec, host, group)));
        setOpen((was) => (was ? { ...was, links: ids, follow: "spec" } : was));
    }, [addSupportNode]);

    // The nodes the open comparison is kept on, while any of its sub-nodes is still there
    const savedTo = useMemo(() => {
        if (!links) return null;
        const hosts = supportNodes.filter((record) => links.includes(record.id)).map((record) => record.hostId);
        return hosts.length ? hosts : null;
    }, [links, supportNodes]);

    const { popOut } = dock;
    const popOutCompare = useCallback(() => popOut("Compare nodes"), [popOut]);

    const value = useMemo(() => ({
        spec: open?.spec ?? null,
        openCompare, openCompareNode, openDriftNode, closeCompare: dock.close,
    }), [open, openCompare, openCompareNode, openDriftNode, dock.close]);

    return (
        <CompareContext.Provider value={value}>
            {children}
            {open && createPortal(
                <HostWindowContext.Provider value={dock.hostWindow}>
                    <ComparePanel
                        key={open.key}
                        initialSpec={open.spec}
                        placement={dock.placement}
                        savedTo={savedTo}
                        onSpecChange={savedTo ? followSpec : undefined}
                        onSave={saveToNodes}
                        onPopOut={popOutCompare}
                        onDock={dock.dockIn}
                        onClose={dock.close}
                    />
                </HostWindowContext.Provider>,
                dock.hostEl,
            )}
        </CompareContext.Provider>
    );
}

export function useCompare() {
    return useContext(CompareContext);
}
