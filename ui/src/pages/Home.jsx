// pages/Home.jsx
import { useState } from "react";

import Header from "../elements/Header.jsx";
import SpinnerModal from "../elements/SpinnerModal.jsx";
import UploadBox from "../elements/UploadBox.jsx";

import '../styles/Home.css';

/* The sample datasets offered under the upload box. Each file is read by the server from its
   provided_datasets/ folder, by name. */
const SAMPLE_DATASETS = [
  { file: "stackoverflow_db_uncleaned_original.csv", label: <>StackOverflow<br />Survey</> },
  { file: "games.csv", label: <>Video Game<br />Sales</> },
  { file: "complaints-2025-04-21_17_31.csv", label: "Student Loan Complaints" },
];

export default function Home( { onSuccess } ) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);

  /* Both ways in - a sample dataset or the user's own file - end the same way: the server's reply is handed
     to onSuccess, or its failure is shown under the upload box. A refusal can come as an error status or as
     {success: false} - a file that isn't a table, say - and either shows the server's own reason when it gives one. */
  async function runUpload(fetchPromise) {
    setUploading(true);
    setUploadError(null);

    try {
      const response = await fetchPromise;
      const data = await response.json().catch(() => null);

      if (!response.ok || !data?.success) {
        throw new Error(data?.error || `Upload failed: ${response.status}`);
      }

      onSuccess(data);
    } catch (err) {
      console.error("Upload error:", err);
      setUploadError(err.message);
    } finally {
      setUploading(false);
    }
  }

  function loadDataset(path) {
    const url = "/api/preloaded?file=" + encodeURIComponent(path);
    return runUpload(fetch(url, { method: "GET" }));
  }

  function fileUpload(uploadedFile) {
    const fileToSend = new FormData();
    fileToSend.append("file", uploadedFile);
    return runUpload(fetch("/api/upload", { method: "POST", body: fileToSend }));
  }

  return (
    <div className="fullscreen-bg">
      <SpinnerModal visible={uploading} />

      <Header />
      <div className="ui-nav-box">
        <div id="placeholder-message">
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
              {SAMPLE_DATASETS.map((dataset) => (
                <div
                  key={dataset.file}
                  className="dataset-button"
                  onClick={() => loadDataset(dataset.file)}
                  role="button"
                  tabIndex={0}
                >
                  {dataset.label}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
