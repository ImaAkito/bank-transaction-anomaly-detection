import { useEffect, useState } from "react";

/** Простой маршрутизатор на основе hash: #/transactions, #/clients/C00001 ... */
export function useRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const [route, setRoute] = useState<string[]>(read);
  useEffect(() => {
    const handler = () => setRoute(read());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  return route;
}

export const link = (...parts: string[]) => `#/${parts.map(encodeURIComponent).join("/")}`;
