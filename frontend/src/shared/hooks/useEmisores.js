import { createContext, createElement, useCallback, useContext, useEffect, useState } from "react";
import { API_BASE, fetchAuth } from "./fetchAuth";

const EmisoresContext = createContext(null);

export function EmisoresProvider({ children }) {
  const [emisores, setEmisores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [emisorActivoRfc, setEmisorActivoRfc] = useState(null);
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await fetchAuth(`${API_BASE}/admin/emisores`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setEmisores(data);
      setEmisorActivoRfc(prev => (prev && data.some(e => e.rfc === prev)) ? prev : (data[0]?.rfc ?? null));
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { cargar(); }, [cargar]);
  return createElement(
    EmisoresContext.Provider,
    { value: { emisores, loading, error, recargar: cargar, emisorActivoRfc, setEmisorActivoRfc } },
    children,
  );
}

export default function useEmisores() {
  const ctx = useContext(EmisoresContext);
  if (!ctx) throw new Error("useEmisores() debe usarse dentro de <EmisoresProvider>");
  return ctx;
}
