import React from 'react';

import Modal from './Modal.jsx';
import '../styles/SpinnerModal.css'

export default function SpinnerModal({ visible }) {
  return (
    <Modal visible={visible}>
        <div className="spinner-modal-loader" />
        <p>Uploading, please wait...</p>
    </Modal>
  );
}
