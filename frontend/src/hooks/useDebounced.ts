import { useEffect, useRef, useState } from "react";

/** The value, once it has stopped changing for `ms`. Compared by content, so a fresh object with the same fields does not restart the timer. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [settled, setSettled] = useState(value);
  const key = JSON.stringify(value);
  const latest = useRef(value);
  latest.current = value;
  useEffect(() => {
    const t = setTimeout(() => setSettled(latest.current), ms);
    return () => clearTimeout(t);
  }, [key, ms]);
  return settled;
}
