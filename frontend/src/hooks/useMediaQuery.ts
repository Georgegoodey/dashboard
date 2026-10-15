import { useEffect, useState } from "react";

/** Tracks a CSS media query, e.g. useMediaQuery("(max-width: 720px)"). */
export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

/** The width at which the dockable workspace gives way to one full-screen panel (keep in sync with the CSS breakpoint). */
export const MOBILE_QUERY = "(max-width: 720px)";
