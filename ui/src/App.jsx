import Home from './pages/Home'
import Buckaroo from './pages/Buckaroo'
import { useState } from 'react';

export default function App() {

  // Single source of truth for whether the user uploaded
  const [uploaded, setUploaded] = useState(localStorage.getItem("userUploaded") === "yes"); // "yes" or "no"
  const [uploadResponse, setUploadResponse] = useState(JSON.parse(localStorage.getItem("uploadResponse"))); // e.g. "my_uploaded_file.csv"
  // const [uploaded, setUploaded] = useState(false); // "yes" or "no"
  // const [uploadResponse, setUploadResponse] = useState(null); // e.g. "my_uploaded_file.csv"

  console.log("App state - uploaded:", uploaded, "uploadResponse:", uploadResponse);

  return (
    <div>
      {/* Centralized rendering logic lives here in App.jsx */}
      {uploaded ? (
        <Buckaroo onReset={() => { 
          setUploaded(false); 
          localStorage.setItem("userUploaded", "no"); 
          localStorage.setItem("uploadResponse", null);}} 
          uploadResponse={uploadResponse} />
      ) : (
        // Home only handles the upload action and calls onSuccess
        <Home onSuccess={(response) => {
          setUploaded(true);
          setUploadResponse(response);
          localStorage.setItem("userUploaded", "yes");
          localStorage.setItem("uploadResponse", JSON.stringify(response));
          console.log("Upload successful, response:", response);
        }} />
      )}
    </div>
  );
}
