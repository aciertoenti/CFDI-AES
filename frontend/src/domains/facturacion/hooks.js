import { useState, useCallback, useEffect } from "react";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";

export function useFacturas(emisorRfc) {
  const [facturas, setFacturas] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const url = emisorRfc ? `${API_BASE}/facturas?emisor_rfc=${encodeURIComponent(emisorRfc)}` : `${API_BASE}/facturas`;
      const res = await fetchAuth(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setFacturas(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [emisorRfc]);
  useEffect(() => { cargar(); }, [cargar]);
  return { facturas, loading, error, recargar: cargar };
}

// Borradores de factura: fuente de datos aparte (endpoint propio, NO es un
// filtro client-side sobre `facturas`). Solo dispara la carga cuando `activo`
// es true - es una pestaña dentro de "Generadas" que casi nunca esta abierta.
export function useBorradores(activo) {
  const [borradores, setBorradores] = useState([]);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState(null);
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await fetchAuth(`${API_BASE}/facturas/borradores`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setBorradores(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { if (activo) cargar(); }, [activo, cargar]);
  return { borradores, loading, error, recargar: cargar };
}

// Auditoria de borradores eliminados: solo lectura, endpoint propio
// (/facturas/borradores/eliminados). Mismo patron perezoso que useBorradores
// - solo carga cuando la pestaña "Eliminados" esta abierta.
export function useBorradoresEliminados(activo) {
  const [eliminados, setEliminados] = useState([]);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState(null);
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await fetchAuth(`${API_BASE}/facturas/borradores/eliminados`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setEliminados(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { if (activo) cargar(); }, [activo, cargar]);
  return { eliminados, loading, error, recargar: cargar };
}

export function useCostosResumen(emisorRfc) {
  const [datos,   setDatos]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const url = emisorRfc ? `${API_BASE}/facturas/costos-resumen?emisor_rfc=${encodeURIComponent(emisorRfc)}` : `${API_BASE}/facturas/costos-resumen`;
      const res = await fetchAuth(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDatos(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [emisorRfc]);
  useEffect(() => { cargar(); }, [cargar]);
  return { datos, loading, error, recargar: cargar };
}

function formatearMes(fecha) {
  return `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, "0")}`;
}

export function useReporteMensual(mesesAtras = 6) {
  const [datos,   setDatos]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const hoy = new Date();
      const inicio = new Date(hoy.getFullYear(), hoy.getMonth() - (mesesAtras - 1), 1);
      const params = new URLSearchParams({ desde: formatearMes(inicio), hasta: formatearMes(hoy) });
      const res = await fetchAuth(`${API_BASE}/reportes/mensual?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDatos(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [mesesAtras]);
  useEffect(() => { cargar(); }, [cargar]);
  return { datos, loading, error, recargar: cargar };
}

export function useContadorVirtualISRResico(emisorRfc, anio, mes) {
  const [datos,   setDatos]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  useEffect(() => {
    if (!emisorRfc) { setLoading(false); return; }
    (async () => {
      setLoading(true); setError(null);
      try {
        const params = new URLSearchParams({ emisor_rfc: emisorRfc, anio: String(anio), mes: String(mes) });
        const res = await fetchAuth(`${API_BASE}/facturas/contador-virtual/isr-resico?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setDatos(await res.json());
      } catch (e) { setError(e.message); }
      finally { setLoading(false); }
    })();
  }, [emisorRfc, anio, mes]);
  return { datos, loading, error };
}
