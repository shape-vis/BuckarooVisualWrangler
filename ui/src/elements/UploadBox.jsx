import { useRef, useState } from "react";

import "../styles/UploadBox.css";

export default function UploadBox({ fileUpload, disabled = false }) {

  const fileInputRef = useRef(null);
  const [dragOver, setDragOver] = useState(false);

  function handleUploadBoxClick() {
    if (!disabled && fileInputRef.current) fileInputRef.current.click();
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handleUploadBoxClick();
    }
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    fileUpload(file);
    e.target.value = "";
  }

  function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    if (disabled) return;
    setDragOver(true);
  }

  function handleDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }

  function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    if (disabled) return;
    const files = e.dataTransfer?.files;
    if (files && files.length > 0) {
      fileUpload(files[0]);
    }
  }

  return (
    <div
            className={`upload-box ${dragOver ? "dragover" : ""} ${disabled ? "upload-box--disabled" : ""}`}
            id="uploadBox"
            role="button"
            tabIndex={disabled ? -1 : 0}
            aria-label="Upload a CSV file"
            aria-disabled={disabled}
            onClick={handleUploadBoxClick}
            onKeyDown={handleKeyDown}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <input
              ref={fileInputRef}
              type="file"
              id="fileInput"
              accept=".csv"
              hidden
              disabled={disabled}
              onChange={handleFileChange}
            />
            <p>
              Drag a File Here
              <br />
              or
              <br />
              <span>Click to Browse</span>
            </p>
          </div>
  );
}



