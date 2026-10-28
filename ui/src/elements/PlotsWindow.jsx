import "../styles/PlotsWindow.css";

/**
 * The frame every window of the Plots view shares - the attribute plots, the compare window and the
 * support-nodes window: a header with the window's title, anything it says under that, its own actions, and
 * the ways to pop it out or dock it and to close it; then its body.
 *
 * Props:
 *  - title: the window's name
 *  - titleId: an id for the title, for a body that labels itself by it
 *  - subtitle: anything under the title
 *  - actions: the window's own buttons, ahead of pop out and close
 *  - placement: "docked" or "window", which decides whether it offers to pop out or to dock
 *  - onPopOut, onDock: offered only when given - a window that cannot leave the Plots view passes neither
 *  - onClose: offered only when given - the attribute plots cannot be closed
 *  - className: the window's own class, beside the frame's
 *  - children: the body
 */
export default function PlotsWindow({
    title, titleId, subtitle = null, actions = null, placement = "docked", onPopOut, onDock, onClose,
    className = "", children,
}) {
    const poppedOut = placement === "window";

    return (
        <div className={`plots-window ${className}`} role="region" aria-labelledby={titleId}>
            <header className="plots-window-header">
                <div className="plots-window-heading">
                    <h2 id={titleId} className="plots-window-title">{title}</h2>
                    {subtitle && <div className="plots-window-subtitle">{subtitle}</div>}
                </div>
                <div className="plots-window-actions">
                    {actions}
                    {poppedOut && onDock && (
                        <button type="button" className="plots-window-action" onClick={onDock}
                                title="Put this window back in the Plots view">
                            Dock
                        </button>
                    )}
                    {!poppedOut && onPopOut && (
                        <button type="button" className="plots-window-action" onClick={onPopOut}
                                title="Open this in a window of its own">
                            Pop out
                        </button>
                    )}
                    {onClose && (
                        <button type="button" className="plots-window-close" onClick={onClose}
                                aria-label={`Close ${title}`}>
                            ×
                        </button>
                    )}
                </div>
            </header>
            {children}
        </div>
    );
}
