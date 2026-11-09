// Small toggle for section-only choices (e.g. revenue vs units). State lives in the section.
export default function Segmented({ value, options, onChange, label }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => {
        const [v, text] = Array.isArray(o) ? o : [o, o];
        return (
          <button key={v} type="button" aria-pressed={v === value} className={v === value ? 'on' : ''} onClick={() => onChange(v)}>
            {text}
          </button>
        );
      })}
    </div>
  );
}
