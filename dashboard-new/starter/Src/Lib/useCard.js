// One card's result for its current filter values. Keeps the last result on screen while the next loads,
// and remembers results per (card, filters, data version) so switching tabs back doesn't refetch.
import { useEffect, useState } from 'react';
import { comboKey, getCard } from './source.js';

const memo = new Map();

export function useCard(id, filterNames, values, version) {
  const key = `${id}#${comboKey(filterNames, values)}#${version}`;
  const [state, setState] = useState(() => (memo.has(key) ? { result: memo.get(key), loading: false } : { result: null, loading: true }));
  useEffect(() => {
    if (memo.has(key)) {
      setState({ result: memo.get(key), loading: false });
      return undefined;
    }
    let live = true;
    setState((s) => ({ result: s.result, loading: true }));
    getCard(id, filterNames, values).then(
      (result) => {
        if (!result.error || result.notIncluded) memo.set(key, result);
        if (live) setState({ result, loading: false });
      },
      (e) => live && setState({ result: { error: e.message }, loading: false }),
    );
    return () => {
      live = false;
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps -- key covers id, filters and version
  return state;
}
