import { useState } from "react";
import "../styles/CollapsiblePanel.css";


export default function CollapsiblePanel({
  children,
  collapsed = null,
  direction = "left", // "left" | "right"  | "down"
  defaultOpen = true,
  className = ""
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  const isRight = direction === "right";
  const isDown = direction === "down";

  const icon = "☰";

  return (
    <div
      className={`panel ${isOpen ? "open" : "closed"} ${
        isRight ? "collapse-right" : isDown ? "collapse-down" : ""
      } ${className}`}
      data-direction={direction}
    >
      <div className="panel-content">
        {isOpen ? children : <div className="panel-collapse-text">{collapsed}</div>}
      </div>

      <button
        className={`panel-toggle ${isDown ? "panel-toggle--down" : ""}`}
        onClick={() => setIsOpen((o) => !o)}
        aria-expanded={isOpen}
        aria-label={isOpen ? "Collapse panel" : "Expand panel"}
      >
        {icon}
      </button>
    </div>
  );
}


// export default function CollapsiblePanel({
//   initialOpen = true,
//   collapseDirection = "left",
//   title = "Panel",
//   children,
//   style = {},
// }) {
//   const [isOpen, setIsOpen] = useState(Boolean(initialOpen));

//   const classes = [
//     "panel",
//     isOpen ? "open" : "closed",
//     collapseDirection === "right" ? "collapse-right" : "",
//     collapseDirection === "down" ? "collapse-down" : "",
//   ]
//     .filter(Boolean)
//     .join(" ");

//   const toggle = () => setIsOpen((v) => !v);

//   const ariaLabel =
//     isOpen ? `Collapse ${collapseDirection}` : `Expand ${collapseDirection}`;

//   return (
//     <div className={classes} role="region" aria-expanded={isOpen} style={style}>
//       {/* Optional small label/handle when collapsed */}
//       {!isOpen && collapseDirection !== "down" && (
//         <div className="panel-collapse-text" aria-hidden="true">
//           {title}
//         </div>
//       )}

//       <div className="panel-content" aria-hidden={!isOpen}>
//         <h3 style={{ margin: "0 0 8px 0" }}>{title}</h3>
//         <div>{children}</div>
//       </div>

//       {/* Toggle button */}
//       <button
//         className="panel-toggle"
//         onClick={toggle}
//         aria-label={ariaLabel}
//         title={ariaLabel}
//         type="button"
//       >
//         {/* simple chevron that flips */}
//         <svg
//           width="18"
//           height="18"
//           viewBox="0 0 24 24"
//           fill="none"
//           aria-hidden="true"
//         >
//           <path
//             d={
//               isOpen
//                 ? // chevron for closing (points toward collapse direction)
//                   collapseDirection === "right"
//                 ? "M9 6l6 6-6 6"
//                 : collapseDirection === "down"
//                 ? "M6 9l6 6 6-6"
//                 : "M15 6l-6 6 6 6"
//                 : // chevron for opening (opposite direction)
//                   collapseDirection === "right"
//                 ? "M15 6l-6 6 6 6"
//                 : collapseDirection === "down"
//                 ? "M6 15l6-6 6 6"
//                 : "M9 6l6 6-6 6"
//             }
//             stroke="white"
//             strokeWidth="2"
//             strokeLinecap="round"
//             strokeLinejoin="round"
//           />
//         </svg>
//       </button>

//       {/* When open and collapse-down, we show a small horizontal handle at bottom */}
//       {collapseDirection === "down" && (
//         <div
//           className="panel-collapse-text"
//           style={{
//             position: "absolute",
//             left: "50%",
//             transform: "translateX(-50%)",
//             bottom: isOpen ? "6px" : "6px",
//             pointerEvents: "none",
//           }}
//           aria-hidden="true"
//         >
//           {isOpen ? "" : title}
//         </div>
//       )}
//     </div>
//   );
// }

