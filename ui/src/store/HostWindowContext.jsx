import { createContext, useContext } from "react";

/**
 * The window a piece of the page is in - this one, unless CompareContext has popped the compare panel out
 * into a window of its own.
 *
 * Listeners, timers, animation frames and ResizeObservers all belong to a window, and this window's stop or
 * stall for an element living in another: a ResizeObserver is only checked as its own page renders, and a
 * minimised page's timers are throttled. So anything in the compare panel takes them from here, and lists
 * the window as a dependency so it sets itself up again when the panel moves.
 */
export const HostWindowContext = createContext(window);

export function useHostWindow() {
    return useContext(HostWindowContext);
}
