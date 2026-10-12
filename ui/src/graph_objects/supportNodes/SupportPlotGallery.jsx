import {useEffect, useRef, useState} from "react";
import "../../styles/SupportPlot.css";

/**
 * The modal's gallery for a sub-node kind picked from ready-made plots - error plots, drift plots: a grid of
 * cards, each with its own columns and an Add To Node button.
 *
 * Each card asks for its plot only once it scrolls into the gallery's view, so a long gallery does not send
 * every request at once, and keeps its own columns, so changing one card's leaves the rest alone.
 *
 * Props:
 *  - cards: [{id, columns, ...}] - whatever the kind needs to draw one, columns among it
 *  - renderCard: ({card, columns, setColumns, enabled, addButton}) => the card, with addButton in its actions
 *  - onAdd: called with (card, columns) to add that plot to the node
 *  - emptyHint: shown when there are no cards
 *  - wide: larger cards, for plots that carry more
 */

function GalleryItem({card, renderCard, onAdd, scrollRef}) {
    const [columns, setColumns] = useState(card.columns);
    const [visible, setVisible] = useState(false);
    const [added, setAdded] = useState(false);
    const boxRef = useRef(null);

    useEffect(() => {
        if (visible) return undefined;
        const observer = new IntersectionObserver(
            (entries) => { if (entries.some((entry) => entry.isIntersecting)) setVisible(true); },
            {root: scrollRef.current, rootMargin: "120px"},
        );
        observer.observe(boxRef.current);
        return () => observer.disconnect();
    }, [visible, scrollRef]);

    // A short confirmation, since the sub-node appears behind the modal
    useEffect(() => {
        if (!added) return undefined;
        const timer = setTimeout(() => setAdded(false), 1500);
        return () => clearTimeout(timer);
    }, [added]);

    const addButton = (
        <button
            type="button"
            className="support-plot-action support-plot-action--primary"
            onClick={() => { onAdd(card, columns); setAdded(true); }}
        >
            {added ? "Added ✓" : "Add To Node"}
        </button>
    );

    return (
        <div ref={boxRef} className="support-plot-gallery-item">
            {renderCard({card, columns, setColumns, enabled: visible, addButton})}
        </div>
    );
}

export function SupportPlotGallery({cards, renderCard, onAdd, emptyHint, wide = false}) {
    const scrollRef = useRef(null);

    if (cards.length === 0) return <p className="support-plot-gallery-empty">{emptyHint}</p>;

    return (
        <div ref={scrollRef} className={`support-plot-gallery ${wide ? "support-plot-gallery--wide" : ""}`}>
            {cards.map((card) => (
                <GalleryItem key={card.id} card={card} renderCard={renderCard} onAdd={onAdd} scrollRef={scrollRef} />
            ))}
        </div>
    );
}
