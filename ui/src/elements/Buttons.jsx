
import "./Buttons.css";

export function RotatedButton({ children, isSelected, onClick, style = {}, ref = null }) {
  return (
    <div
      ref={ref}
      className={`rotatedButton ${isSelected ? "rotatedButton--selected" : ""}`}
      onClick={onClick}
      style={style}
    >
      <span className="rotatedButtonText">
        {children}
      </span>
    </div>
  );
}

export function StandardButton({ children, isSelected, onClick, style = {} }) {
  return (
    <div
      className={`standardButton ${isSelected ? "standardButton--selected" : ""}`}
      onClick={onClick}
      style={style}
    >
        <span className="standardButtonText">
            {children}
        </span>
    </div>
  );
}