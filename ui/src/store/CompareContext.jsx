import {
    createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState,
} from "react";
import { createPortal } from "react-dom";

import ComparePanel from "../elements/ComparePanel.jsx";
import { usePgraph } from "./PGraphContext.jsx";
import { HostWindowContext } from "./HostWindowContext.jsx";
import { normalizeSpec, specFromPair } from "../utils/comparisonSpec.js";
import {
    restrictionsOf, savedPlotViewConfig, specOfPlotView,
} from "../graph_objects/supportNodes/plotView.js";

/**
 * The open comparison, and where it is shown: docked as a tab in the Plots view, or popped out into a
 * browser window of its own that can be dragged anywhere, another monitor included.
 *
 * The panel is rendered once, into a detached element this provider owns, and that element is moved
 * between the dock's slot and the popup's body. Moving a node leaves the React tree under it alone, so
 * docking and popping out keep everything the panel holds - its options, its zoom, the plot it already
 * fetched. Nothing under it remounts when Buckaroo remounts the views after a wrangle, either, since the
 * provider sits outside that.
 *
 * Code inside the panel cannot assume it runs in this window: see HostWindowContext.jsx.
 */

const CompareContext = createContext(null);

const POPUP_NAME = "buckaroo-compare";
const POPUP_BODY_CLASS = "compare-popup-body";
const GEOMETRY_KEY = "buckaroo.compare.popup";
const DEFAULT_POPUP = { width: 1320, height: 860 };

// Where the popup last was, so it opens again on the same monitor. Browser storage can be missing or refuse
function readGeometry() {
    try {
        return JSON.parse(localStorage.getItem(GEOMETRY_KEY)) ?? DEFAULT_POPUP;
    } catch {
        return DEFAULT_POPUP;
    }
}

function saveGeometry(popup) {
    try {
        localStorage.setItem(GEOMETRY_KEY, JSON.stringify({
            width: popup.outerWidth, height: popup.outerHeight, left: popup.screenX, top: popup.screenY,
        }));
    } catch {
        // Not worth troubling anyone over: the popup opens at the default size next time
    }
}

function popupFeatures({ width, height, left, top }) {
    const placed = Number.isFinite(left) && Number.isFinite(top) ? `,left=${left},top=${top}` : "";
    return `popup,width=${width},height=${height}${placed}`;
}

/* Copies this page's stylesheets into the popup, which starts as a blank document. Vite adds and rewrites
   <style> tags as modules load and hot-reload, so the copies are redone whenever the head changes. */
function mirrorStyles(popup) {
    const sync = () => {
        const head = popup.document.head;
        head.querySelectorAll("[data-mirrored]").forEach((node) => node.remove());
        document.head.querySelectorAll('style, link[rel="stylesheet"], link[rel~="icon"]').forEach((node) => {
            const copy = popup.document.importNode(node, true);
            // An absolute href, since the blank popup has no address of its own to resolve against
            if (node.href) copy.href = node.href;
            copy.dataset.mirrored = "";
            head.appendChild(copy);
        });
    };
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(document.head, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
}

/**
 * Props:
 *  - revealPlots: opens the Plots view if it is closed, so a docked comparison has somewhere to show
 */
export function CompareProvider({ revealPlots, children }) {
    const { nodes, serverNodesById, supportNodes, addSupportNode, updateSupportNode } = usePgraph();

    /* The open comparison and a serial for it, which keys the panel so each new one starts fresh. restrict is
       what a plot-view sub-node fixed, and links are the sub-nodes it is kept on - see openPlotView and save. */
    const [open, setOpen] = useState(null);
    const [placement, setPlacement] = useState("docked");
    const [popup, setPopup] = useState(null);
    const [plotsTab, setPlotsTab] = useState("attributes");

    const [hostEl] = useState(() => {
        const element = document.createElement("div");
        element.className = "compare-host";
        return element;
    });
    const slotRef = useRef(null);
    const serial = useRef(0);
    /* The popup this side last closed. Closing a window is not immediate - its pagehide arrives later - so
       this is how that pagehide is told apart from the user closing the window. */
    const closedByApp = useRef(null);

    const show = useCallback((spec, { restrict = null, links = null } = {}) => {
        serial.current += 1;
        setOpen({ spec, key: serial.current, restrict, links });
        if (popup && !popup.closed) {
            popup.focus();
        } else {
            setPlotsTab("compare");
            revealPlots?.();
        }
    }, [popup, revealPlots]);

    /** Compares the two nodes paired in the graph. The same pair again just brings the open one forward. */
    const openCompare = useCallback((pair) => {
        const nodesById = Object.fromEntries(nodes.map((node) => [node.id, node]));
        const spec = specFromPair(pair, nodesById);
        if (open && !open.spec.id && !open.links && open.spec.a === spec.a && open.spec.b === spec.b) {
            if (popup && !popup.closed) popup.focus();
            else { setPlotsTab("compare"); revealPlots?.(); }
            return;
        }
        show(spec);
    }, [nodes, open, popup, show, revealPlots]);

    /** Opens a comparison saved on the graph, as the server returned it. */
    const openSaved = useCallback((spec) => show(normalizeSpec(spec)), [show]);

    /** Opens a plot-view sub-node in the panel, offering only the options it leaves open. Every sub-node one
        Save added changes along with it. The one already open is just brought forward. */
    const openPlotView = useCallback((record) => {
        const links = record.config?.group
            ? supportNodes.filter((one) => one.kind === record.kind && one.config?.group === record.config.group)
                .map((one) => one.id)
            : [record.id];
        if (open?.links?.includes(record.id)) {
            if (popup && !popup.closed) popup.focus();
            else { setPlotsTab("compare"); revealPlots?.(); }
            return;
        }
        const columns = Object.keys(serverNodesById?.[record.hostId]?.data?.metrics?.columns ?? {});
        show(specOfPlotView(record, columns), { restrict: restrictionsOf(record.config), links });
    }, [supportNodes, serverNodesById, open, popup, show, revealPlots]);

    // While a comparison is kept on sub-nodes, they follow its settings
    const links = open?.links;
    const followSpec = useCallback((spec) => {
        links?.forEach((id) => updateSupportNode(id, (record) => ({ config: { ...record.config, spec } })));
    }, [links, updateSupportNode]);

    /* Keeps the open comparison beside both its nodes, as a full comparison on each, and from then on they
       follow it. Grouped, so opening either later changes both. */
    const saveToNodes = useCallback((spec) => {
        const group = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
        const ids = [...new Set([spec.a, spec.b])]
            .map((host) => addSupportNode(host, "plotView", savedPlotViewConfig(spec, host, group)));
        setOpen((was) => (was ? { ...was, links: ids } : was));
    }, [addSupportNode]);

    // The nodes the open comparison is kept on, while any of its sub-nodes is still there
    const savedTo = useMemo(() => {
        if (!links) return null;
        const hosts = supportNodes.filter((record) => links.includes(record.id)).map((record) => record.hostId);
        return hosts.length ? hosts : null;
    }, [links, supportNodes]);

    // The popup's own document goes when the popup does, so the host comes back to this one first
    const reclaimHost = useCallback(() => {
        if (hostEl.ownerDocument !== document) document.adoptNode(hostEl);
    }, [hostEl]);

    const closePopup = useCallback(() => {
        if (!popup || popup.closed) return;
        saveGeometry(popup);
        closedByApp.current = popup;
        popup.close();
    }, [popup]);

    const closeCompare = useCallback(() => {
        closePopup();
        reclaimHost();
        setPopup(null);
        setPlacement("docked");
        setOpen(null);
        setPlotsTab("attributes");
    }, [closePopup, reclaimHost]);

    /* Moves the panel into a window of its own. Called straight from a click: a popup opened any later is
       one the browser blocks. If it is blocked anyway, the panel simply stays docked. */
    const popOut = useCallback(() => {
        const win = window.open("", POPUP_NAME, popupFeatures(readGeometry()));
        if (!win) return;

        const doc = win.document;
        // A window reused by name can still hold an earlier session's panel
        doc.head.replaceChildren();
        doc.body.replaceChildren();
        doc.title = "Compare nodes · Buckaroo";
        const base = doc.createElement("base");
        base.href = `${window.location.origin}/`;
        doc.head.appendChild(base);
        doc.body.className = POPUP_BODY_CLASS;
        doc.body.appendChild(hostEl);
        win.focus();

        setPopup(win);
        setPlacement("window");
    }, [hostEl]);

    /** Brings a popped-out panel back into its tab. */
    const dockIn = useCallback(() => {
        reclaimHost();
        slotRef.current?.appendChild(hostEl);
        closePopup();
        setPopup(null);
        setPlacement("docked");
        setPlotsTab("compare");
        revealPlots?.();
    }, [hostEl, reclaimHost, closePopup, revealPlots]);

    // The popup's styles, how it closes and where it was left
    useEffect(() => {
        if (!popup) return undefined;
        const stopMirroring = mirrorStyles(popup);
        const onResize = () => saveGeometry(popup);
        const onPageHide = () => {
            if (closedByApp.current === popup) return;
            saveGeometry(popup);
            // Closing the window ends the comparison, as closing a tab would; Dock is the way back in
            closeCompare();
        };
        popup.addEventListener("resize", onResize);
        popup.addEventListener("pagehide", onPageHide);
        return () => {
            stopMirroring();
            popup.removeEventListener("resize", onResize);
            popup.removeEventListener("pagehide", onPageHide);
        };
    }, [popup, closeCompare]);

    // A popup outlives the page that opened it unless told otherwise - on reload, and when Buckaroo goes
    useEffect(() => {
        if (!popup) return undefined;
        const close = () => {
            closedByApp.current = popup;
            popup.close();
        };
        window.addEventListener("pagehide", close);
        return () => {
            window.removeEventListener("pagehide", close);
            // Also runs once the popup is done with - closing a closed window does nothing
            close();
        };
    }, [popup]);

    /* The dock's slot, as a callback ref. The Plots view mounts a new one after every wrangle, and the panel
       moves into whichever is current while it is docked. */
    const placementRef = useRef(placement);
    useLayoutEffect(() => {
        placementRef.current = placement;
        if (placement === "docked") slotRef.current?.appendChild(hostEl);
    }, [placement, hostEl]);
    const dockSlot = useCallback((slot) => {
        slotRef.current = slot;
        if (slot && placementRef.current === "docked") slot.appendChild(hostEl);
    }, [hostEl]);

    const hostWindow = placement === "window" && popup ? popup : window;

    const value = useMemo(() => ({
        spec: open?.spec ?? null,
        placement, plotsTab, setPlotsTab,
        openCompare, openSaved, openPlotView, closeCompare, popOut, dockIn, dockSlot,
    }), [open, placement, plotsTab, openCompare, openSaved, openPlotView, closeCompare, popOut, dockIn, dockSlot]);

    return (
        <CompareContext.Provider value={value}>
            {children}
            {open && createPortal(
                <HostWindowContext.Provider value={hostWindow}>
                    <ComparePanel
                        key={open.key}
                        initialSpec={open.spec}
                        restrict={open.restrict}
                        placement={placement}
                        savedTo={savedTo}
                        onSpecChange={savedTo ? followSpec : undefined}
                        onSave={saveToNodes}
                        onPopOut={popOut}
                        onDock={dockIn}
                        onClose={closeCompare}
                    />
                </HostWindowContext.Provider>,
                hostEl,
            )}
        </CompareContext.Provider>
    );
}

export function useCompare() {
    return useContext(CompareContext);
}
