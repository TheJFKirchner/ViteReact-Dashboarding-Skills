import { renderCommentary } from '../Lib/commentary.js';

const Segments = ({ segments }) =>
  segments.map((s, i) => (s.missing ? <mark key={i} className="missing">{s.text}</mark> : <span key={i}>{s.text}</span>));

/** Commentary text with live numbers: metrics = the card's Analysis result "metrics" for the current filters. */
export default function Commentary({ markdown, metrics }) {
  const { blocks } = renderCommentary(markdown, metrics ?? {});
  return (
    <div className="commentary">
      {blocks.map((b, i) =>
        b.type === 'list' ? (
          <ul key={i}>{b.items.map((segs, j) => <li key={j}><Segments segments={segs} /></li>)}</ul>
        ) : (
          <p key={i}><Segments segments={b.segments} /></p>
        ),
      )}
    </div>
  );
}
