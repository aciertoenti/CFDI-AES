import { useCallback, useState } from "react";
import { API_BASE, fetchAuth } from "./fetchAuth";

export default function useResumenEjecutivo() {
  const [resultado, setResultado] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const generar = useCallback(async payload => {
    setLoading(true); setError(null); setResultado(null);
    try {
      const res = await fetchAuth(`${API_BASE}/ia/resumen-ejecutivo`, {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP ${res.status}`);
      }
      setResultado(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  return { resultado, generar, loading, error };
}
