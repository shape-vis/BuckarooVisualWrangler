import {useCallback, useMemo, useRef, useState} from "react";
import {ATTRIBUTES_TAB, PlotsWindowsContext} from "./plotsWindows.js";

/* The Plots view's windows: which tab is showing, and the tabs of the windows docked in it - see plotsWindows.js,
   which holds the context and the hooks that read it, useDockableWindow among them. */

/**
 * Props:
 *  - revealPlots: opens the Plots view if it is closed, so a docked window has somewhere to show
 */
export function PlotsWindowsProvider({ revealPlots, children }) {
    const [activeTab, setActiveTab] = useState(ATTRIBUTES_TAB);
    // The windows docked in the view, in the order they opened: {id, label, dockSlot}
    const [docked, setDocked] = useState([]);
    // How to bring each popped-out window forward, by id
    const popups = useRef(new Map());

    const dockWindow = useCallback((entry) => {
        setDocked((current) => [...current.filter((one) => one.id !== entry.id), entry]);
    }, []);

    const undockWindow = useCallback((id) => {
        setDocked((current) => current.filter((one) => one.id !== id));
    }, []);

    const setPopupFocus = useCallback((id, focus) => {
        if (focus) popups.current.set(id, focus);
        else popups.current.delete(id);
    }, []);

    /** Brings a window into view: its popup, when it has one, or else its tab in the Plots view. */
    const showWindow = useCallback((id) => {
        const focusPopup = popups.current.get(id);
        if (focusPopup) {
            focusPopup();
            return;
        }
        setActiveTab(id);
        revealPlots?.();
    }, [revealPlots]);

    // A window leaving the view hands its tab back to the attribute plots, if it was the one showing
    const leaveTab = useCallback((id) => {
        setActiveTab((current) => (current === id ? ATTRIBUTES_TAB : current));
    }, []);

    const value = useMemo(() => ({
        activeTab, setActiveTab, docked,
        dockWindow, undockWindow, setPopupFocus, showWindow, leaveTab,
    }), [activeTab, docked, dockWindow, undockWindow, setPopupFocus, showWindow, leaveTab]);

    return (
        <PlotsWindowsContext.Provider value={value}>
            {children}
        </PlotsWindowsContext.Provider>
    );
}
