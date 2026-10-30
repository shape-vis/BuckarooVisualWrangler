import React from 'react';

import Modal from './Modal.jsx';
import '../styles/SpinnerModal.css'

export default function SpinnerModal({ visible }) {
  return (
    <Modal visible={visible}>
        <div className="spinner-modal-loader" />
        <p>Uploading and profiling, please wait...</p>
        <p className="spinner-modal-help-text">Large CSVs can take 30-60 seconds while Buckaroo writes the table and runs detectors.</p>
    </Modal>
  );
}
