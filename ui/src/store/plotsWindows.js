import {createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState} from "react";

/**
 * The windows of the Plots view: the attribute plots, always there, and the windows opened over them - the
 * compare window and the support-nodes window. Each sits as a tab in the Plots view, and a window that allows it
 * can be popped out into a browser window of its own, dragged anywhere, another monitor included.
 *
 * The provider, in PlotsWindowsContext.jsx, holds what the windows share: which tab is showing, and the tabs of
 * the windows docked in the view. This holds the context and the hooks that read it. Each window's own placement
 * - docked or popped out - is useDockableWindow's, below, which every window but the attribute plots is built on.
 *
 * Code inside a window that can pop out cannot assume it runs in this window: see HostWindowContext.jsx.
 */

export const PlotsWindowsContext = createContext(null);

// The attribute plots' tab, which is always there and the one shown when nothing else is
export const ATTRIBUTES_TAB = "attributes";

const POPUP_BODY_CLASS = "plots-window-popup-body";
const DEFAULT_POPUP = { width: 1320, height: 860 };

const geometryKey = (id) => `buckaroo.${id}.popup`;

// Where a window's popup last was, so it opens again on the same monitor. Browser storage can be missing or refuse
function readGeometry(id) {
    try {
        return JSON.parse(localStorage.getItem(geometryKey(id))) ?? DEFAULT_POPUP;
    } catch {
        return DEFAULT_POPUP;
    }
}

function saveGeometry(id, popup) {
    try {
        localStorage.setItem(geometryKey(id), JSON.stringify({
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

/** What the Plots view's windows share - see PlotsWindowsContext.jsx. */
export function usePlotsWindows() {
    return useContext(PlotsWindowsContext);
}

/**
 * One window of the Plots view that can be docked as a tab or popped out: the base the compare window and the
 * support-nodes window are built on.
 *
 * The window's content is rendered once, by its owner, into a detached element this hook keeps (hostEl), and
 * that element is moved between the dock's slot and the popup's body. Moving a node leaves the React tree under
 * it alone, so docking and popping out keep everything the window holds. Nothing under it remounts when
 * Buckaroo remounts the views after a wrangle, either, so long as its owner sits outside that.
 *
 * Takes:
 *  - id: the window's tab id, and the name its popup and remembered geometry go by
 *  - label: its tab's text
 *  - open: whether the owner is showing it
 *  - onClose: what closing it means to the owner - called once the window itself is put away
 *
 * Returns {hostEl, placement, hostWindow, popOut, dockIn, close}. hostWindow is the window the content is
 * in, for HostWindowContext.
 */
export function useDockableWindow({ id, label, open, onClose }) {
    const { dockWindow, undockWindow, setPopupFocus, showWindow, leaveTab } = usePlotsWindows();

    const [hostEl] = useState(() => {
        const element = document.createElement("div");
        element.className = "plots-window-host";
        return element;
    });
    const [placement, setPlacement] = useState("docked");
    const [popup, setPopup] = useState(null);
    const slotRef = useRef(null);
    /* The popup this side last closed. Closing a window is not immediate - its pagehide arrives later - so
       this is how that pagehide is told apart from the user closing the window. */
    const closedByApp = useRef(null);

    // The owner's close as it is now, so close below stays the same function across the owner's renders
    const onCloseRef = useRef(onClose);
    useLayoutEffect(() => {
        onCloseRef.current = onClose;
    });

    // The popup's own document goes when the popup does, so the host comes back to this one first
    const reclaimHost = useCallback(() => {
        if (hostEl.ownerDocument !== document) document.adoptNode(hostEl);
    }, [hostEl]);

    const closePopup = useCallback(() => {
        if (!popup || popup.closed) return;
        saveGeometry(id, popup);
        closedByApp.current = popup;
        popup.close();
    }, [popup, id]);

    const close = useCallback(() => {
        closePopup();
        reclaimHost();
        setPopup(null);
        setPlacement("docked");
        leaveTab(id);
        onCloseRef.current?.();
    }, [closePopup, reclaimHost, leaveTab, id]);

    /* Moves the window into one of its own. Called straight from a click: a popup opened any later is one the
       browser blocks. If it is blocked anyway, the window simply stays docked. */
    const popOut = useCallback((title) => {
        const win = window.open("", `buckaroo-${id}`, popupFeatures(readGeometry(id)));
        if (!win) return;

        const doc = win.document;
        // A window reused by name can still hold an earlier session's content
        doc.head.replaceChildren();
        doc.body.replaceChildren();
        doc.title = `${title} · Buckaroo`;
        const base = doc.createElement("base");
        base.href = `${window.location.origin}/`;
        doc.head.appendChild(base);
        doc.body.className = POPUP_BODY_CLASS;
        doc.body.appendChild(hostEl);
        win.focus();

        setPopup(win);
        setPlacement("window");
        leaveTab(id);
    }, [hostEl, id, leaveTab]);

    /** Brings a popped-out window back into its tab. */
    const dockIn = useCallback(() => {
        reclaimHost();
        slotRef.current?.appendChild(hostEl);
        closePopup();
        setPopup(null);
        setPlacement("docked");
        // The popup is going, so showing the window means its tab - not focusing the popup on its way out
        setPopupFocus(id, null);
        showWindow(id);
    }, [hostEl, reclaimHost, closePopup, setPopupFocus, showWindow, id]);

    // The popup's styles, how it closes and where it was left
    useEffect(() => {
        if (!popup) return undefined;
        const stopMirroring = mirrorStyles(popup);
        const onResize = () => saveGeometry(id, popup);
        const onPageHide = () => {
            if (closedByApp.current === popup) return;
            saveGeometry(id, popup);
            // Closing the window ends what it shows, as closing a tab would; Dock is the way back in
            close();
        };
        popup.addEventListener("resize", onResize);
        popup.addEventListener("pagehide", onPageHide);
        return () => {
            stopMirroring();
            popup.removeEventListener("resize", onResize);
            popup.removeEventListener("pagehide", onPageHide);
        };
    }, [popup, close, id]);

    // A popup outlives the page that opened it unless told otherwise - on reload, and when Buckaroo goes
    useEffect(() => {
        if (!popup) return undefined;
        const closeIt = () => {
            closedByApp.current = popup;
            popup.close();
        };
        window.addEventListener("pagehide", closeIt);
        return () => {
            window.removeEventListener("pagehide", closeIt);
            // Also runs once the popup is done with - closing a closed window does nothing
            closeIt();
        };
    }, [popup]);

    // While popped out, bringing the window forward focuses its popup rather than a tab
    useEffect(() => {
        if (!popup) return undefined;
        setPopupFocus(id, () => popup.focus());
        return () => setPopupFocus(id, null);
    }, [popup, id, setPopupFocus]);

    /* The dock's slot, as a callback ref. The Plots view mounts a new one after every wrangle, and the content
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

    // A docked window has a tab, for as long as it is open
    const isDocked = open && placement === "docked";
    useEffect(() => {
        if (!isDocked) return undefined;
        dockWindow({ id, label, dockSlot });
        return () => undockWindow(id);
    }, [isDocked, id, label, dockSlot, dockWindow, undockWindow]);

    let hostWindow = window;
    if (placement === "window" && popup) {
        hostWindow = popup;
    }

    return { hostEl, placement, hostWindow, popOut, dockIn, close };
}
