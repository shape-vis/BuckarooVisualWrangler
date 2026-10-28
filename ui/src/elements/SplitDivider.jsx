import { useCallback, useRef } from "react";

import "../styles/SplitDivider.css";

/**
 * The drag handle between the two main views. It sits between them as a flex item and reports the share of
 * their combined width the left one should take; Buckaroo turns that into the two views' flex-grow.
 *
 * A drag redraws both views - the plot matrix lays itself out again at every width - so the share is
 * sent at most once a frame.
 */

// Neither view can be squeezed narrower than this, or its toolbar and axes stop fitting
const MIN_VIEW_WIDTH = 280;
// Arrow keys move the divider by this share, for anyone not dragging
const KEY_STEP = 0.02;
export const DEFAULT_SPLIT = 0.5;

// How far each arrow key moves the divider; any other key leaves it
const KEY_STEPS = { ArrowLeft: -KEY_STEP, ArrowRight: KEY_STEP };

// The width the two views have between them, read from either side of the divider
function viewsWidth(divider) {
    const leftWidth = divider.previousElementSibling.getBoundingClientRect().width;
    const rightWidth = divider.nextElementSibling.getBoundingClientRect().width;
    return leftWidth + rightWidth;
}

/**
 * Props:
 *  - split: the left view's share of the two views' width, between 0 and 1
 *  - onSplit: called with the next share; double-clicking resets it to DEFAULT_SPLIT
 */
export default function SplitDivider({ split, onSplit }) {
    // Null unless a drag is in flight
    const dragRef = useRef(null);
    const frameRef = useRef(0);

    // The share range that keeps both views at least MIN_VIEW_WIDTH, from the width they have between them
    const clampFor = (total) => {
        const min = Math.min(0.5, MIN_VIEW_WIDTH / Math.max(total, 1));
        return (value) => Math.min(1 - min, Math.max(min, value));
    };

    const onPointerDown = useCallback((event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        const divider = event.currentTarget;
        const total = viewsWidth(divider);
        divider.setPointerCapture(event.pointerId);
        dragRef.current = { startX: event.clientX, startSplit: split, total, clamp: clampFor(total) };
    }, [split]);

    const onPointerMove = useCallback((event) => {
        const drag = dragRef.current;
        if (!drag) return;
        const next = drag.clamp(drag.startSplit + (event.clientX - drag.startX) / drag.total);
        cancelAnimationFrame(frameRef.current);
        frameRef.current = requestAnimationFrame(() => onSplit(next));
    }, [onSplit]);

    const onPointerUp = useCallback((event) => {
        if (!dragRef.current) return;
        dragRef.current = null;
        event.currentTarget.releasePointerCapture(event.pointerId);
    }, []);

    const onKeyDown = (event) => {
        const step = KEY_STEPS[event.key] ?? 0;
        if (!step) return;
        event.preventDefault();
        const total = viewsWidth(event.currentTarget);
        const clamp = clampFor(total);
        onSplit(clamp(split + step));
    };

    return (
        <div
            className="split-divider"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize views"
            aria-valuenow={Math.round(split * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            tabIndex={0}
            title="Drag to resize, double-click to split evenly"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onDoubleClick={() => onSplit(DEFAULT_SPLIT)}
            onKeyDown={onKeyDown}
        />
    );
}
