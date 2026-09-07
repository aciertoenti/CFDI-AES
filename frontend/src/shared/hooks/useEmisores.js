import { createContext, createElement, useCallback, useContext, useEffect, useState } from "react";
import { API_BASE, fetchAuth } from "./fetchAuth";

const EmisoresContext = createContext(null);

// Preferencia "emisor activo" persistida en localStorage, scopeada por RFC
// personal del usuario: sobrevive a logout/login y a recargar la pagina.
// Antes vivia solo en estado React y se recalculaba como "primer Activo" en
// cada montaje del Provider, ignorando lo que el usuario habia elegido -
// bug zg5r8Rk. Toda lectura/escritura va envuelta en try/catch: si
// localStorage no esta disponible (modo privado, politica del navegador) se
// degrada al comportamiento anterior (arranca en null) sin romper la app.
const PREFIJO_CLAVE_EMISOR = "cfdi.emisorActivoRfc.";
const claveEmisor = (rfcPersonal) => `${PREFIJO_CLAVE_EMISOR}${rfcPersonal}`;

function leerEmisorPersistido(rfcPersonal) {
  if (!rfcPersonal) return null;
  try {
    return localStorage.getItem(claveEmisor(rfcPersonal));
  } catch {
    return null;
  }
}

// Higiene para logout (se llama desde App.jsx): conserva SOLO la preferencia
// del usuario que cierra sesion - para que su proximo login la recupere - y
// borra las de cualquier otro usuario que haya usado este navegador. Asi no
// se acumulan claves viejas: tras un logout queda a lo sumo 1 clave de este
// tipo en localStorage.
export function limpiarEmisoresPersistidos(rfcPersonalAConservar) {
  // sin RFC no se distingue "la mía" de "las otras" - no borrar nada (antes
  // esto arrasaba TODAS las claves, incluida la del usuario que sale, cuando
  // usuarioActual ya era null al momento de logout - zg5r8Rk).
  if (!rfcPersonalAConservar) return;
  try {
    const conservar = claveEmisor(rfcPersonalAConservar);
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k && k.startsWith(PREFIJO_CLAVE_EMISOR) && k !== conservar) {
        localStorage.removeItem(k);
      }
    }
  } catch {
    /* localStorage no disponible - nada que limpiar */
  }
}

export function EmisoresProvider({ children, rfcPersonal = null }) {
  const [emisores, setEmisores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Semilla desde localStorage en el primer render (no null a ciegas): lo que
  // el usuario dejo seleccionado la ultima vez. cargar() valida abajo que ese
  // emisor siga existiendo y Activo antes de quedarse con el.
  const [emisorActivoRfc, setEmisorActivoRfc] = useState(() => leerEmisorPersistido(rfcPersonal));
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await fetchAuth(`${API_BASE}/admin/emisores`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setEmisores(data);
      // Se conserva la seleccion previa (prev = estado actual o el valor
      // persistido leido al montar) SOLO si ese emisor sigue en la lista Y
      // sigue Activo. Si dejo de existir o se volvio Inactivo, se cae al
      // fallback (primer Activo, luego data[0]) - nunca se aterriza a
      // proposito en un emisor Inactivo, que reactivaria la pantalla de
      // bloqueo del bug zg5WRPk.
      setEmisorActivoRfc(prev => {
        const prevSigueValido = prev && data.some(e => e.rfc === prev && e.estado === "Activo");
        return prevSigueValido
          ? prev
          : (data.find(e => e.estado === "Activo")?.rfc ?? data[0]?.rfc ?? null);
      });
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { cargar(); }, [cargar]);
  // Persiste cada cambio de seleccion: manual (tarjeta de la pantalla
  // Emisores o el selector del header) o el recalculo de cargar(). Mismo
  // try/catch de seguridad. No se borra la clave cuando queda null (caso sin
  // emisores): es inofensivo, el guard de cargar() la rechaza en el proximo
  // montaje.
  useEffect(() => {
    if (!rfcPersonal || !emisorActivoRfc) return;
    try {
      localStorage.setItem(claveEmisor(rfcPersonal), emisorActivoRfc);
    } catch {
      /* localStorage no disponible, degradar sin romper */
    }
  }, [emisorActivoRfc, rfcPersonal]);
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
