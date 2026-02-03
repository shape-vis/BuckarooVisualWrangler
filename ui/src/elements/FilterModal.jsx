import React from 'react';

import './FilterModal.css'
import Modal from './Modal.jsx';
import { StandardButton } from './Buttons.jsx';
import HistogramBarChart from '../visualizations/HistogramBarChart.jsx';

export default function FilterModal({ visible, attribute, onClose, onApply, table_name, errorColors }) {
  return (
    <Modal visible={visible}>
        <h2>Filter by {attribute}</h2>
        <svg width="400" height="400">
        <HistogramBarChart attribute={attribute}  cellID={"filterModalHistogram"}  pos={{x: 50, y: 20}} size={{w:300, h:300}} table_name={table_name} attrX={attribute}  errorColors={errorColors} />
        </svg>
        <StandardButton onClick={() => onClose()}>Close</StandardButton>
        <StandardButton onClick={() => onApply()}>Apply Filter</StandardButton>
    </Modal>
);
}
