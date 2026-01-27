import './Modal.css'

export default function Modal ({ children, visible }) {
  // show/hide via React prop
  if (!visible) return null;
  return (
    <div id="modal" className="modal" style={{ display: "block" }}>
      <div className="modal-content">
        {children}
      </div>
    </div>
  );
}
