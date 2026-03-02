// src/App.jsx
import { useRef, useState } from "react";

import Header from "../elements/Header.jsx";
import SpinnerModal from "../elements/SpinnerModal.jsx";
import UploadBox from "../elements/UploadBox.jsx";

import './Home.css';

export default function Home( { onSuccess } ) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);

  // NOTE: ensure these files live under `public/static/data/...` so they are available at these paths
  async function loadDataset(path) {
    console.log("Loading dataset:", path);

    setUploading(true);

    try {
      const response = await fetch("/api/preloaded?file=" + encodeURIComponent(path), {
        method: "GET",
      });

      if (!response.ok) {
        throw new Error(`Upload failed: ${response.status}`);
      }

      const data = await response.json();

      onSuccess(data);

    } catch (err) {
      console.error("Upload error:", err);
      setUploadError(err.message);
    } finally {
      setUploading(false);
    }
  }


  async function fileUpload(uploadedFile) {
    const fileToSend = new FormData();
    fileToSend.append("file", uploadedFile);

    setUploading(true);

    try {
      const response = await fetch("/api/upload", {
        method: "POST",
        body: fileToSend,
      });

      if (!response.ok) {
        throw new Error(`Upload failed: ${response.status}`);
      }

      const data = await response.json();

      onSuccess(data);

    } catch (err) {
      console.error("Upload error:", err);
      setUploadError(err.message);
    } finally {
      setUploading(false);
    }
  }
    


  return (
    <div className="fullscreen-bg">
      <SpinnerModal visible={uploading} />

      <Header />
      <div className="ui-nav-box">
        <div
          id="placeholder-message"
          style={{ textAlign: "center", fontSize: "40px", color: "darkslategrey" }}
        >
          <div>Welcome to Buckaroo!</div>
          <div style={{ fontSize: "24px", marginTop: "10px", color: "gray" }}>
            <p>Start by uploading your own or selecting a sample dataset:</p>

            <UploadBox fileUpload={fileUpload} />

            {uploadError && (
              <div className="error-box">
                {uploadError}
              </div>
            )}

            <p style={{ marginTop: "24px", marginBottom: 0 }}>Sample Datasets</p>

            <div style={{ display: "flex", margin: "auto", justifyContent: "center", gap: 12 }}>
              <div
                className="dataset-button"
                onClick={() => loadDataset("stackoverflow_db_uncleaned.csv")}
                role="button"
                tabIndex={0}
              >
                StackOverflow
                <br />
                Survey
              </div>

              <div
                className="dataset-button"
                onClick={() =>
                  loadDataset("Crimes_-_One_year_prior_to_present_20250421.csv")
                }
                role="button"
                tabIndex={0}
              >
                Chicago
                <br />
                Crime
              </div>

              <div
                className="dataset-button"
                onClick={() => loadDataset("complaints-2025-04-21_17_31.csv")}
                role="button"
                tabIndex={0}
              >
                Student Loan Complaints
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

