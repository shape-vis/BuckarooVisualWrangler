
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

export function NavButton({ children, isSelected, onClick, style = {}, icon }) {
  return (
      <div
          className={`navButton ${isSelected ? "navButtonButton--selected" : ""}`}
          onClick={onClick}
          style={style}
      >
        <span className="navButtonButtonText">
            {children}
        </span>
      </div>
  );
}

export function IconButton({ children, onClick, title, style = {} }) {
  return (
      <button
          className="iconButton"
          onClick={onClick}
          title={title}
          style={style}
      >
        {children}
      </button>
  );
}