import {useEffect, useRef, useState} from "react";
import {useHostWindow} from "../../store/HostWindowContext.jsx";
import "../../styles/SupportPlot.css";

/**
 * The support-nodes window's gallery for a sub-node kind picked from ready-made plots - error plots, drift plots:
 * a grid of cards, each with its own columns and an Add To Node button. Or, for plots with a lot to show - drift
 * plots carry the compare window's zoom strip, hover note and legend - one card a page, filling the window, with
 * a pager over it.
 *
 * Each card asks for its plot only once it comes into view - scrolled to, or paged to - so a long gallery does not
 * send every request at once, and keeps its own columns, so changing one card's leaves the rest alone. The
 * observer and timers are the host window's, since the window can be popped out - see HostWindowContext.jsx.
 *
 * Props:
 *  - cards: [{id, columns, label?, ...}] - whatever the kind needs to draw one, columns among it; label names its
 *    page
 *  - renderCard: ({card, columns, setColumns, enabled, addButton}) => the card, with addButton in its actions
 *  - onAdd: called with (card, columns) to add that plot to the node
 *  - emptyHint: shown when there are no cards
 *  - paged: one card a page, filling the room the gallery is given, rather than a grid
 */

function GalleryItem({card, renderCard, onAdd, hidden = false}) {
    const hostWindow = useHostWindow();
    const [columns, setColumns] = useState(card.columns);
    const [visible, setVisible] = useState(false);
    const [added, setAdded] = useState(false);
    const boxRef = useRef(null);

    useEffect(() => {
        if (visible) return undefined;
        const observer = new hostWindow.IntersectionObserver(
            (entries) => { if (entries.some((entry) => entry.isIntersecting)) setVisible(true); },
            {rootMargin: "120px"},
        );
        observer.observe(boxRef.current);
        return () => observer.disconnect();
    }, [visible, hostWindow]);

    // A short confirmation, since the sub-node appears in the graph rather than here
    useEffect(() => {
        if (!added) return undefined;
        const timer = hostWindow.setTimeout(() => setAdded(false), 1500);
        return () => hostWindow.clearTimeout(timer);
    }, [added, hostWindow]);

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
        <div ref={boxRef} className="support-plot-gallery-item" hidden={hidden}>
            {renderCard({card, columns, setColumns, enabled: visible, addButton})}
        </div>
    );
}

// What a card's page is called in the pager: its label, or its columns
function pageLabel(card) {
    if (card.label) return card.label;
    return card.columns.join(" × ");
}

/* One card a page, filling the gallery's room. Every card stays mounted - so each keeps its columns, and a page
   already looked at shows again at once - but only the current one is shown, and a card is only drawn once it has
   been paged to. */
function PagedGallery({cards, renderCard, onAdd}) {
    const [page, setPage] = useState(0);
    // The cards can shrink under a page - fewer attributes selected - so the page is held to the last one
    const lastPage = cards.length - 1;
    const shown = Math.min(page, lastPage);

    const goTo = (next) => setPage(Math.max(0, Math.min(next, lastPage)));

    return (
        <div className="support-plot-pages">
            <div className="support-plot-pager" role="navigation" aria-label="Plot pages">
                <button
                    type="button"
                    className="support-plot-pager-step"
                    onClick={() => goTo(shown - 1)}
                    disabled={shown === 0}
                    aria-label="Previous plot"
                >
                    ‹ Previous
                </button>
                <div className="support-plot-pager-pages">
                    {cards.map((card, index) => (
                        <button
                            key={card.id}
                            type="button"
                            className={`support-plot-pager-page ${index === shown ? "support-plot-pager-page--current" : ""}`}
                            aria-current={index === shown ? "page" : undefined}
                            onClick={() => goTo(index)}
                            title={pageLabel(card)}
                        >
                            {pageLabel(card)}
                        </button>
                    ))}
                </div>
                <span className="support-plot-pager-count">{shown + 1} of {cards.length}</span>
                <button
                    type="button"
                    className="support-plot-pager-step"
                    onClick={() => goTo(shown + 1)}
                    disabled={shown === lastPage}
                    aria-label="Next plot"
                >
                    Next ›
                </button>
            </div>
            <div className="support-plot-page">
                {cards.map((card, index) => (
                    <GalleryItem
                        key={card.id}
                        card={card}
                        renderCard={renderCard}
                        onAdd={onAdd}
                        hidden={index !== shown}
                    />
                ))}
            </div>
        </div>
    );
}

export function SupportPlotGallery({cards, renderCard, onAdd, emptyHint, paged = false}) {
    if (cards.length === 0) return <p className="support-plot-gallery-empty">{emptyHint}</p>;

    if (paged) {
        return <PagedGallery cards={cards} renderCard={renderCard} onAdd={onAdd} />;
    }

    return (
        <div className="support-plot-gallery">
            {cards.map((card) => (
                <GalleryItem key={card.id} card={card} renderCard={renderCard} onAdd={onAdd} />
            ))}
        </div>
    );
}
