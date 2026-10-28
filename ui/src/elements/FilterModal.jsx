import Modal from './Modal.jsx';
import { StandardButton } from './Buttons.jsx';
import HistogramBarChart from '../visualizations/HistogramBarChart.jsx';

// Defined once at module level so the chart sees the same objects on every
// render; a fresh object would make it redraw each time the modal re-renders.
const HISTOGRAM_POS = { x: 50, y: 20 };
const HISTOGRAM_SIZE = { w: 300, h: 300 };

export default function FilterModal({ visible, attribute, onClose, onApply, errorColors }) {
  return (
    <Modal visible={visible}>
        <h2>Filter by {attribute}</h2>
        <svg width="400" height="400">
        <HistogramBarChart
          cellID={"filterModalHistogram"}
          pos={HISTOGRAM_POS}
          size={HISTOGRAM_SIZE}
          attrX={attribute}
          errorColors={errorColors}
        />
        </svg>
        <StandardButton onClick={onClose}>Close</StandardButton>
        <StandardButton onClick={() => onApply()}>Apply Filter</StandardButton>
    </Modal>
);
}
