
import "../styles/Buttons.css";

export function RotatedButton({ children, isSelected, onClick, className = "", ref = null }) {
  return (
    <div
      ref={ref}
      className={`rotatedButton ${isSelected ? "rotatedButton--selected" : ""} ${className}`}
      onClick={onClick}
    >
      <span className="rotatedButtonText">
        {children}
      </span>
    </div>
  );
}

export function StandardButton({ children, isSelected, onClick, className = "" }) {
  return (
    <div
      className={`standardButton ${isSelected ? "standardButton--selected" : ""} ${className}`}
      onClick={onClick}
    >
        <span className="standardButtonText">
            {children}
        </span>
    </div>
  );
}

export function NavButton({ children, isSelected, onClick, className = "", icon }) {
  return (
      <button
          type="button"
          className={`navButton ${isSelected ? "navButton--selected" : ""} ${className}`}
          aria-pressed={isSelected}
          onClick={onClick}
      >
        {icon && <span className="navButtonIcon">{icon}</span>}
        <span className="navButtonButtonText">
            {children}
        </span>
      </button>
  );
}

export function IconButton({ children, onClick, title, className = "" }) {
  return (
      <button
          className={`iconButton ${className}`}
          onClick={onClick}
          title={title}
      >
        {children}
      </button>
  );
}
