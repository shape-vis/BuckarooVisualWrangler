import React from 'react';

import './FilterModal.css'
import Modal from './Modal.jsx';
import { StandardButton } from './Buttons.jsx';

export default function FilterModal({ visible, attribute, onClose, onApply }) {
  return (
    <Modal visible={visible}>
        <h2>Filter by {attribute}</h2>
        <StandardButton onClick={() => onClose()}>Close</StandardButton>
        <StandardButton onClick={() => onApply()}>Apply Filter</StandardButton>
    </Modal>
);
}
