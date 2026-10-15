import { useEffect, useState } from "react";
import { storage } from "@/lib";

/** useState that survives reloads. The stored string is accepted only if `isValid` says so; otherwise `fallback` wins. */
export function useStoredState<T extends string>(key: string, fallback: () => T, isValid: (v: string) => v is T) {
  const [value, setValue] = useState<T>(() => {
    const saved = storage.get(key);
    return saved !== null && isValid(saved) ? saved : fallback();
  });
  useEffect(() => storage.set(key, value), [key, value]);
  return [value, setValue] as const;
}
