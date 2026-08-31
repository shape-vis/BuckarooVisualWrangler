import { useCallback, useRef } from "react";

import RepairPanel from "./RepairPanel.jsx";
import QualityPanel from "./QualityPanel.jsx";
import { useDock, MIN_DOCK_WIDTH } from "../store/DockContext.jsx";

import "../styles/RightDock.css";

/**
 * The right-hand dock: the repair and quality panels as selectable tabs in one resizable pane,
 * the way an editor stacks open files.
 *
 * Both panels stay mounted whichever tab is showing, so switching away does not throw away generated
 * previews or an already-fetched trajectory.
 */

// Type scales with the dock, so dragging it wider buys readability rather than just whitespace. Every
// length inside the panels is in em, so they all follow from this one number.
const MIN_FONT = 12;
const MAX_FONT = 19;
const PX_PER_FONT_STEP = 45;

const fontForWidth = (width) =>
  Math.min(MAX_FONT, MIN_FONT + (width - MIN_DOCK_WIDTH) / PX_PER_FONT_STEP);

const TABS = [
  { id: "repair", label: "Repair" },
  { id: "quality", label: "Quality" },
];

export default function RightDock() {
  const {
    activeTab, setActiveTab,
    collapsed, revealTab, hideDock,
    width, setWidth, resetWidth,
  } = useDock();

  // Null unless a resize drag is in flight
  const dragRef = useRef(null);

  const onResizeStart = useCallback((event) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { startX: event.clientX, startWidth: width };
  }, [width]);

  const onResizeMove = useCallback((event) => {
    if (!dragRef.current) return;
    // The dock is anchored right, so dragging left - a falling clientX - widens it
    setWidth(dragRef.current.startWidth + (dragRef.current.startX - event.clientX));
  }, [setWidth]);

  const onResizeEnd = useCallback((event) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  if (collapsed) {
    return (
      <div className="right-dock right-dock--collapsed">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className="right-dock-rail-tab"
            onClick={() => revealTab(tab.id)}
            title={`Show ${tab.label}`}
          >
            {tab.label}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="right-dock" style={{ width, fontSize: `${fontForWidth(width)}px` }}>
      <div
        className="right-dock-resize"
        onPointerDown={onResizeStart}
        onPointerMove={onResizeMove}
        onPointerUp={onResizeEnd}
        onPointerCancel={onResizeEnd}
        onDoubleClick={resetWidth}
        title="Drag to resize, double-click to reset"
        role="separator"
        aria-orientation="vertical"
      />

      <div className="right-dock-tabstrip">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`right-dock-tab ${activeTab === tab.id ? "right-dock-tab--active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
        <button
          className="right-dock-hide"
          onClick={hideDock}
          title="Hide panels"
          aria-label="Hide panels"
        >
          &#8250;
        </button>
      </div>

      <div className="right-dock-body">
        <div className="right-dock-pane" hidden={activeTab !== "repair"}>
          <RepairPanel />
        </div>
        <div className="right-dock-pane" hidden={activeTab !== "quality"}>
          <QualityPanel />
        </div>
      </div>
    </div>
  );
}
