import {useCallback, useMemo, useState} from "react";
import {supportId} from "../utils/graphTopology.js";
import {randomKey} from "../utils/randomKey.js";
import {anchorOf, getSupportType} from "../graph_objects/supportNodes/registry.js";
import {usePlotsWindows} from "./plotsWindows.js";

// The support-nodes window's tab in the Plots view
export const SUPPORT_WINDOW_ID = "support";

/* The size an error plot grows to while it is being wrangled on - room for the matrix's own plot, its axes and
   the footer with Repair */
export const WRANGLE_SIZE = {width: 460, height: 500};

/* The side a new sub-node of this kind goes on: the one its kind fixes, if it fixes one. Otherwise "auto", and
   the layout puts it on the side its host's branch leans to, worked out each time the graph is drawn
   (supportLayout's branchSides). */
function initialSide(supportType) {
    const preferred = supportType?.side;
    if (preferred === "left" || preferred === "right") return preferred;
    return "auto";
}

/* How the user is looking at the sub-nodes, kept apart from the records: a host's eye hides all of that host's
   (hiddenHosts), a sub-node's own minimise hides just it (minimized), and the graph's two toggles hide every
   sub-node beside a node, or beside an edge. */
const NO_HIDING = Object.freeze({
    hiddenHosts: new Set(),
    minimized: new Set(),
    hideSide: false,
    hideEdge: false,
});

const toggleKeyOf = (record) => (anchorOf(record) === "edge" ? "hideEdge" : "hideSide");

/** Whether a record is drawn under these hiding choices - its host being drawn is the graph's business. */
function isShownIn(view, record) {
    if (view.hiddenHosts.has(record.hostId)) return false;
    if (view.minimized.has(record.id)) return false;
    return !view[toggleKeyOf(record)];
}

/**
 * The hiding choices that show exactly shownIds, each hidden the way it already was where that still holds.
 * A host's eye stays shut, and a graph-wide toggle on, only while nothing it covers is to be shown; anything else
 * not to be shown that they no longer cover becomes a minimise of its own, so it stays hidden.
 */
function viewShowing(view, records, shownIds) {
    const hiddenHosts = new Set();
    for (const hostId of view.hiddenHosts) {
        const showsOne = records.some((record) => record.hostId === hostId && shownIds.has(record.id));
        if (!showsOne) hiddenHosts.add(hostId);
    }

    const next = {hiddenHosts, minimized: new Set(), hideSide: view.hideSide, hideEdge: view.hideEdge};
    for (const record of records) {
        if (shownIds.has(record.id)) next[toggleKeyOf(record)] = false;
    }

    for (const record of records) {
        if (shownIds.has(record.id)) continue;
        if (!isShownIn(next, record)) continue;
        next.minimized.add(record.id);
    }
    return next;
}

/** The hiding choices with these records shown too, and everything else looking as it did. */
function viewRevealing(view, records, ids) {
    const shownIds = new Set(ids);
    for (const record of records) {
        if (isShownIn(view, record)) shownIds.add(record.id);
    }
    return viewShowing(view, records, shownIds);
}

/**
 * The supporting sub-nodes the user has hung beside nodes, how they are being looked at, and the window that
 * adds them.
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
 * so hiding never touches what would be saved. A hidden sub-node is not gone: it shows as a badge on its host
 * (SupportBadges), which brings it back. The records and the hiding are one state, so a change to both - adding
 * a sub-node where its kind is hidden, which shows it - lands at once.
 */
export function useSupportNodes() {
    const {showWindow} = usePlotsWindows();

    const [state, setState] = useState({records: [], view: NO_HIDING});
    const supportNodes = state.records;
    const view = state.view;

    // The node the support-nodes window adds to, while it is open
    const [supportWindowHost, setSupportWindowHost] = useState(null);

    /* The error plot being wrangled on, if any: {id, sizeBefore}. It is drawn large, with the matrix's own plot to
       brush and Repair beside it; sizeBefore is what it goes back to after. */
    const [wrangling, setWrangling] = useState(null);

    // How many there are of each anchor, for the graph-wide toggles
    const supportCountByAnchor = useMemo(() => {
        const counts = {side: 0, edge: 0};
        supportNodes.forEach((record) => { counts[anchorOf(record)] += 1; });
        return counts;
    }, [supportNodes]);

    /* Whether a record is drawn, as far as hiding goes. A new function whenever what is hidden changes, so the
       graph's draw, which depends on it, runs again. */
    const isSupportShown = useCallback((record) => isShownIn(view, record), [view]);

    /* A host's eye: hides every sub-node it has, beside it and beside its incoming edge, while any of them shows;
       once none does, shows them all again - its single minimises included. */
    const toggleSupportHidden = useCallback((hostId) => {
        setState((current) => {
            const ofHost = current.records.filter((record) => record.hostId === hostId);
            const anyShown = ofHost.some((record) => isShownIn(current.view, record));

            if (anyShown) {
                const hiddenHosts = new Set(current.view.hiddenHosts);
                hiddenHosts.add(hostId);
                return {...current, view: {...current.view, hiddenHosts}};
            }

            const ids = ofHost.map((record) => record.id);
            return {...current, view: viewRevealing(current.view, current.records, ids)};
        });
    }, []);

    // Hides one sub-node, which leaves a badge on its host
    const minimizeSupportNode = useCallback((id) => {
        setState((current) => {
            const minimized = new Set(current.view.minimized);
            minimized.add(id);
            return {...current, view: {...current.view, minimized}};
        });
    }, []);

    /* Shows one hidden sub-node again - its badge's click - and only it: whatever hid it, everything else it hid
       stays hidden. */
    const restoreSupportNode = useCallback((id) => {
        setState((current) => ({...current, view: viewRevealing(current.view, current.records, [id])}));
    }, []);

    // The graph's toggles, one per anchor. Each takes a value or a function of the current one, as a setter does
    const setHideAll = useCallback((key, next) => {
        setState((current) => {
            let hidden = next;
            if (typeof next === "function") hidden = next(current.view[key]);
            return {...current, view: {...current.view, [key]: hidden}};
        });
    }, []);
    const setHideAllNodeSupports = useCallback((next) => setHideAll("hideSide", next), [setHideAll]);
    const setHideAllEdgeSupports = useCallback((next) => setHideAll("hideEdge", next), [setHideAll]);

    // Returns the new sub-node's id, so whatever added it can find it again
    const addSupportNode = useCallback((hostId, kind, config) => {
        const id = supportId(hostId, randomKey());
        const supportType = getSupportType(kind);
        const record = {
            id,
            hostId,
            kind,
            side: initialSide(supportType),
            config,
            createdAt: new Date().toISOString(),
        };

        // A new one shows even where its kind or its host's are hidden, or it would seem to vanish
        setState((current) => {
            const records = [...current.records, record];
            return {records, view: viewRevealing(current.view, records, [id])};
        });
        return id;
    }, []);

    // patch is merged into the record, or is a function of the record that returns what to merge
    const updateSupportNode = useCallback((id, patch) => {
        setState((current) => {
            const records = current.records.map((record) => {
                if (record.id !== id) return record;

                let changes = patch;
                if (typeof patch === "function") changes = patch(record);
                return {...record, ...changes};
            });
            return {...current, records};
        });
    }, []);

    const removeSupportNode = useCallback((id) => {
        setState((current) => {
            const records = current.records.filter((record) => record.id !== id);
            return {...current, records};
        });
        setWrangling((current) => (current?.id === id ? null : current));
    }, []);

    // Every sub-node of these hosts - for a candidate that is declined, whose node is gone with it
    const removeSupportNodesOf = useCallback((hostIds) => {
        const gone = new Set(hostIds);
        setState((current) => {
            const records = current.records.filter((record) => !gone.has(record.hostId));
            return {...current, records};
        });
    }, []);

    /** Opens the support-nodes window on a node, and brings it into view. */
    const openSupportWindow = useCallback((hostId) => {
        setSupportWindowHost(hostId);
        showWindow(SUPPORT_WINDOW_ID);
    }, [showWindow]);
    const closeSupportWindow = useCallback(() => setSupportWindowHost(null), []);

    /** Grows an error plot to be wrangled on - see ErrorPlotSupport. Only one is wrangled on at a time. */
    const startWrangling = useCallback((record) => {
        setWrangling({id: record.id, sizeBefore: record.size ?? null});
        updateSupportNode(record.id, {size: WRANGLE_SIZE});
    }, [updateSupportNode]);

    /** Puts the error plot being wrangled on back to the size it was. */
    const endWrangling = useCallback(() => {
        if (!wrangling) return;
        updateSupportNode(wrangling.id, {size: wrangling.sizeBefore});
        setWrangling(null);
    }, [wrangling, updateSupportNode]);

    return {
        supportNodes, addSupportNode, updateSupportNode, removeSupportNode, removeSupportNodesOf,
        supportWindowHost, openSupportWindow, closeSupportWindow,
        toggleSupportHidden,
        minimizeSupportNode, restoreSupportNode,
        supportCountByAnchor, isSupportShown,
        hideAllNodeSupports: view.hideSide, setHideAllNodeSupports,
        hideAllEdgeSupports: view.hideEdge, setHideAllEdgeSupports,
        wranglingSupportId: wrangling?.id ?? null, startWrangling, endWrangling,
    };
}
