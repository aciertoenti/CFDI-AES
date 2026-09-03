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
      // Al inicializar (sin seleccion previa valida) preferir el primer emisor
      // Activo, no data[0] a ciegas: si la API devuelve un emisor Inactivo
      // primero (ej. uno viejo dado de baja, por orden de id), el usuario caia
      // en la pantalla de bloqueo de "Emisor Inactivo" en cada login aunque
      // tuviera un emisor Activo. data[0] queda solo como ultimo recurso: si
      // no hay ninguno Activo, el bloqueo si es correcto (no hay con que facturar).
      setEmisorActivoRfc(prev =>
        (prev && data.some(e => e.rfc === prev))
          ? prev
          : (data.find(e => e.estado === "Activo")?.rfc ?? data[0]?.rfc ?? null)
      );
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { cargar(); }, [cargar]);
  // Fuente unica de "el emisor activo y si esta Inactivo" - antes se
  // recalculaba por separado en NuevaFactura.jsx y AppShell.jsx con su
  // propio find(), con riesgo de desincronizarse. find() plano, sin
  // fallback a emisores[0]: si emisorActivoRfc es null, emisorActivo debe
  // ser undefined, no el primer emisor de la lista por accidente.
  const emisorActivo = emisores.find(e => e.rfc === emisorActivoRfc);
  const emisorInactivo = !!emisorActivo && emisorActivo.estado === "Inactivo";
  return createElement(
    EmisoresContext.Provider,
    { value: { emisores, loading, error, recargar: cargar, emisorActivoRfc, setEmisorActivoRfc, emisorActivo, emisorInactivo } },
    children,
  );
}

export default function useEmisores() {
  const ctx = useContext(EmisoresContext);
  if (!ctx) throw new Error("useEmisores() debe usarse dentro de <EmisoresProvider>");
  return ctx;
}
