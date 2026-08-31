import { createContext, useCallback, useContext, useState } from "react";

/**
 * State for the right-hand dock: which panel tab is showing, whether it is collapsed, and how wide it
 * has been dragged.
 *
 * This lives in a context rather than inside RightDock for two reasons. The dock renders inside the
 * container Buckaroo remounts after every wrangle (key={refreshKey}), so component state there would
 * reset the user's width and tab each time. And it lets the panels ask to be shown by simply calling
 * revealTab from the handler that decided it - no trigger counters, and no effects mirroring them.
 */

export const MIN_DOCK_WIDTH = 260;
export const MAX_DOCK_WIDTH = 900;
export const DEFAULT_DOCK_WIDTH = 300;

const DockContext = createContext(null);

export function DockProvider({ children }) {
    const [activeTab, setActiveTab] = useState("repair");
    const [collapsed, setCollapsed] = useState(true);
    const [width, setWidthState] = useState(DEFAULT_DOCK_WIDTH);

    /** Show a panel: select its tab and open the dock if it was put away. */
    const revealTab = useCallback((tab) => {
        setActiveTab(tab);
        setCollapsed(false);
    }, []);

    const hideDock = useCallback(() => setCollapsed(true), []);

    const setWidth = useCallback((next) => {
        setWidthState(Math.min(MAX_DOCK_WIDTH, Math.max(MIN_DOCK_WIDTH, next)));
    }, []);

    const resetWidth = useCallback(() => setWidthState(DEFAULT_DOCK_WIDTH), []);

    return (
        <DockContext.Provider value={{
            activeTab, setActiveTab,
            collapsed, setCollapsed,
            revealTab, hideDock,
            width, setWidth, resetWidth,
        }}>
            {children}
        </DockContext.Provider>
    );
}

export function useDock() {
    return useContext(DockContext);
}
