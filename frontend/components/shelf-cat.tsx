/**
 * A small cat walking along a shelf at the bottom of the sidebar.
 * Pure CSS (see globals.css, "Shelf cat"): decorative, hidden from assistive tech.
 * Legs start inside the body and swing around the hip, so they always stay attached;
 * the far pair is paler for depth and moves in the opposite phase (diagonal gait).
 */
export function ShelfCat() {
  return (
    <div className="cat-track" aria-hidden>
      <svg className="cat" viewBox="0 0 36 24" width="36" height="24">
        <g className="cat-body">
          <path className="cat-tail" d="M9 11.4 C4.2 11.6 3 6.6 5.6 3.6" />
          <line className="cat-leg cat-far cat-back cat-a" x1="13.6" y1="12" x2="13.6" y2="21" />
          <line className="cat-leg cat-far cat-front cat-b" x1="24" y1="12" x2="24" y2="21" />
          <path d="M8.6 11.6 C8.6 8.6 11.2 7.8 15 7.9 H22.4 C25.8 7.9 27 10 26.7 12.4 C26.4 14.9 24.2 15.8 21.6 15.7 H12.6 C10.1 15.7 8.6 14.3 8.6 11.6 Z" />
          <line className="cat-leg cat-back cat-b" x1="11" y1="12" x2="11" y2="21" />
          <line className="cat-leg cat-front cat-a" x1="21.6" y1="12" x2="21.6" y2="21" />
          <g className="cat-head">
            <path className="cat-ears" d="M24.7 5.4 L25.2 0.8 L28 3.4 Z M29.2 3.2 L32 1 L32.3 5.6 Z" />
            <circle cx="28.6" cy="7.6" r="4.3" />
            <ellipse cx="32.2" cy="9.2" rx="1.7" ry="1.3" />
            <ellipse className="cat-eye" cx="30.1" cy="6.9" rx="0.75" ry="0.8" />
            <path className="cat-collar" d="M25 10.1 Q28.1 12.2 31.2 10.2" />
          </g>
        </g>
      </svg>
    </div>
  );
}
