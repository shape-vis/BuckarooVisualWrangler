import { useRef, useState } from "react";

import "../styles/UploadBox.css";

export default function UploadBox({ fileUpload }) {

  const fileInputRef = useRef(null);
  const [dragOver, setDragOver] = useState(false);

  function handleUploadBoxClick() {
    if (fileInputRef.current) fileInputRef.current.click();
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    fileUpload(file);
  }

  function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
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
    const files = e.dataTransfer?.files;
    if (files && files.length > 0) {
      fileUpload(files[0]);
    }
  }

  return (
    <div
            className={`upload-box ${dragOver ? "dragover" : ""}`}
            id="uploadBox"
            onClick={handleUploadBoxClick}
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



