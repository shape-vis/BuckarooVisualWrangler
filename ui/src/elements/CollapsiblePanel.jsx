import { useState } from "react";
import "../styles/CollapsiblePanel.css";

// Extra class on the panel for each collapse direction. "left" is the default
// layout and needs none.
const DIRECTION_CLASS = {
  left: "",
  right: "collapse-right",
  down: "collapse-down",
};

export default function CollapsiblePanel({
  children,
  collapsed = null,
  direction = "left", // "left" | "right"  | "down"
  defaultOpen = true,
  className = "",
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  const isDown = direction === "down";
  const openClass = isOpen ? "open" : "closed";
  const directionClass = DIRECTION_CLASS[direction] ?? "";
  const toggleClass = isDown ? "panel-toggle--down" : "";

  const icon = "☰";

  return (
    <div
      className={`panel ${openClass} ${directionClass} ${className}`}
      data-direction={direction}
    >
      <div className="panel-content">
        {isOpen ? children : <div className="panel-collapse-text">{collapsed}</div>}
      </div>

      <button
        className={`panel-toggle ${toggleClass}`}
        onClick={() => setIsOpen((o) => !o)}
        aria-expanded={isOpen}
        aria-label={isOpen ? "Collapse panel" : "Expand panel"}
      >
        {icon}
      </button>
    </div>
  );
}
