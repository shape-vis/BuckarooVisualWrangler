import Home from './pages/Home'
import Buckaroo from './pages/Buckaroo'
import { useState } from 'react';
import { TableNameProvider } from './store/TableNameContext.jsx';
import { LoadingProvider } from './store/LoadingContext.jsx';

// The upload is remembered for the browser tab, so reloading the page stays on the dataset
function readStoredUploadResponse() {
  return JSON.parse(sessionStorage.getItem("uploadResponse"));
}

export default function App() {

  // Whether a dataset has been uploaded, stored as "yes" or "no"
  const [uploaded, setUploaded] = useState(() => sessionStorage.getItem("userUploaded") === "yes");
  // The server's reply to the upload, which names the table it created
  const [uploadResponse, setUploadResponse] = useState(readStoredUploadResponse);

  function handleReset() {
    setUploaded(false);
    sessionStorage.setItem("userUploaded", "no");
    sessionStorage.setItem("uploadResponse", null);
  }

  function handleUploadSuccess(response) {
    setUploaded(true);
    setUploadResponse(response);
    sessionStorage.setItem("userUploaded", "yes");
    sessionStorage.setItem("uploadResponse", JSON.stringify(response));
  }

  return (
    <div>
      {uploaded ? (
        <TableNameProvider initialTableName={uploadResponse?.table_name}>
          <LoadingProvider>
            <Buckaroo onReset={handleReset} />
          </LoadingProvider>
        </TableNameProvider>
      ) : (
        // Home only handles the upload action and calls onSuccess
        <Home onSuccess={handleUploadSuccess} />
      )}
    </div>
  );
}
