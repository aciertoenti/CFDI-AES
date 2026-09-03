import { useCallback, useEffect, useState } from "react";
import { API_BASE, fetchAuth } from "./fetchAuth";

export default function useClientes() {
  const [clientes, setClientes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await fetchAuth(`${API_BASE}/admin/clientes`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setClientes(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { cargar(); }, [cargar]);
  return { clientes, loading, error, recargar: cargar };
}
