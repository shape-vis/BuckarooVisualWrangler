// src/App.jsx
import { useState } from "react";

import Header from "../elements/Header.jsx";
import SpinnerModal from "../elements/SpinnerModal.jsx";
import UploadBox from "../elements/UploadBox.jsx";
import { logInteractionEvent } from "../utils/interactionLogger.jsx";

import '../styles/Home.css';

export default function Home( { onSuccess } ) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);

  function handleUploadSuccess(data) {
    if (data?.timings) {
      console.info("[Buckaroo Upload Timings]", data.timings);
    }
    logInteractionEvent("csv_upload_completed", {
      table: data?.table_name,
      rows: data?.["rows for undetected data"],
      errorRows: data?.rows_for_detected,
      timings: data?.timings,
    });
    onSuccess(data);
  }

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

      handleUploadSuccess(data);

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

      handleUploadSuccess(data);

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
        <div id="placeholder-message">
          <img
            src="/images/favicon/web-app-manifest-512x512.png"
            alt="Buckaroo mascot riding a horse with a lasso"
            className="mascot-image"
          />
          <div>Welcome to Buckaroo!</div>
          <div className="placeholder-subtitle">
            <p>Start by uploading your own or selecting a sample dataset:</p>

            <UploadBox fileUpload={fileUpload} />

            {uploadError && (
              <div className="error-box">
                {uploadError}
              </div>
            )}

            <p className="sample-datasets-heading">Sample Datasets</p>

            <div className="dataset-button-row">
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
                  loadDataset("crimes.csv")
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

