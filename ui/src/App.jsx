import Home from './pages/Home'
import Buckaroo from './pages/Buckaroo'
import { useState } from 'react';
import { TableNameProvider } from './store/TableNameContext.jsx';
import { LoadingProvider } from './store/LoadingContext.jsx';

export default function App() {

  // Single source of truth for whether the user uploaded
  const [uploaded, setUploaded] = useState(sessionStorage.getItem("userUploaded") === "yes"); // "yes" or "no"
  const [uploadResponse, setUploadResponse] = useState(JSON.parse(sessionStorage.getItem("uploadResponse"))); // e.g. "my_uploaded_file.csv"
  // const [uploaded, setUploaded] = useState(false); // "yes" or "no"
  // const [uploadResponse, setUploadResponse] = useState(null); // e.g. "my_uploaded_file.csv"

  console.log("App state - uploaded:", uploaded, "uploadResponse:", uploadResponse);

  return (
    <div>
      {/* Centralized rendering logic lives here in App.jsx */}
      {uploaded ? (
        <TableNameProvider initialTableName={uploadResponse?.table_name}>
          <LoadingProvider>
            <Buckaroo onReset={() => {
              setUploaded(false);
              sessionStorage.setItem("userUploaded", "no");
              sessionStorage.setItem("uploadResponse", null);}}
            />
          </LoadingProvider>
        </TableNameProvider>
      ) : (
        // Home only handles the upload action and calls onSuccess
        <Home onSuccess={(response) => {
          setUploaded(true);
          setUploadResponse(response);
          sessionStorage.setItem("userUploaded", "yes");
          sessionStorage.setItem("uploadResponse", JSON.stringify(response));
          console.log("Upload successful, response:", response);
        }} />
      )}
    </div>
  );
}
