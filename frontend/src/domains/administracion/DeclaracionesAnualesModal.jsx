import { useEffect, useRef, useState } from "react";
import { useToast } from "../../shared/layout/ToastProvider";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Btn, Card } from "../../shared/components/atoms";
import { C, detalleError } from "../../shared/utils/format";

// Declaraciones anuales - modal de documentos (Parte B, 22 sep 2026;
// validación por CONTENIDO del PDF, reporte 189, 23 sep 2026; borrado de
// declaración completa, reporte 189b; REDISEÑO del flujo de subida,
// reporte 189d, 23 sep 2026).
//
// Reporte 189d - motivo real (prueba real del usuario, tras 189/189b):
// - El formulario seguía pidiendo ejercicio/tipo/tipo de documento aunque
//   el sistema YA los detecta del PDF - campos redundantes que además
//   invitaban a error (el usuario podía "corregir" algo que el servidor
//   de todas formas iba a ignorar).
// - Un PDF cualquiera (no un acuse real) se guardaba igual, como
//   declaración "manual" - el backend (main.py, R1) ya NO lo permite:
//   un documento NO_RECONOCIDO se rechaza (422), nunca se guarda.
// - El flujo ahora es MULTI-ARCHIVO: se eligen/arrastran uno o varios
//   PDF, cada uno se analiza (solo lectura, nunca guarda nada) y se
//   muestra en una lista de resultados con su estado (válido/duplicado/
//   rechazado) - "Guardar N acuses" guarda solo los válidos, uno por
//   uno; un fallo no detiene a los demás.
// - Ya no hay "tarjeta de confirmación" de un solo archivo ni campos
//   editables de ejercicio/tipo - todo sale siempre del documento.
//
// Accesibilidad (WCAG 2.2 AA, pedido explicito desde 188): foco atrapado
// dentro del dialog, Escape cierra, el foco vuelve al boton que abrio el
// modal al cerrar, role="dialog" + aria-modal, aria-live en la lista de
// resultados del análisis (un lector de pantalla se entera del estado de
// cada archivo sin tener que navegar a buscarlo).
//
// Guardia de cambios sin guardar (188, adaptada en 189d): las 4 vías de
// cierre (fondo/Esc/X/Cancelar) pasan por solicitarCierre(), que
// intercepta con una confirmación DENTRO del modal (role="alertdialog",
// nunca window.confirm) SOLO si hay al menos un acuse VÁLIDO sin guardar
// - un archivo rechazado o duplicado NUNCA ensucia el formulario (bug
// real encontrado en la prueba: antes cualquier archivo elegido, aunque
// fuera rechazado, disparaba la confirmación sin que hubiera nada que
// perder). Ver seguirEditando()/descartar() abajo.

const MAX_MB = 5; // mismo default que MAX_DECLARACION_PDF_BYTES del backend

// Mismo texto exacto que MENSAJE_NUMERO_OPERACION_DUPLICADO en main.py -
// se compara literal (no substring) para distinguir "duplicado" de
// cualquier otro rechazo y mostrar el texto corto que pide R2 ("Ya está
// registrado") en vez del mensaje completo del servidor. Si el texto del
// servidor cambia algún día sin actualizar esto, el peor caso es que el
// archivo se muestre como "rechazado" con el mensaje completo - sigue
// siendo correcto y legible, solo pierde la etiqueta corta.
const MENSAJE_DUPLICADO_SERVIDOR = "Ya existe una declaración registrada con este número de operación";

const ETIQUETA_TIPO_DECLARACION = { normal: "Normal", complementaria: "Complementaria" };

// El input nativo NO se oculta con display:none (eso lo saca del arbol
// de accesibilidad) - aquí sí se usa aria-hidden+tabIndex=-1 a propósito
// (distinto del <SelectorArchivo> de un solo archivo, ver justificación
// junto al dropzone abajo): el DIV que lo envuelve ya es un control
// accesible completo por sí mismo (role="button", operable con teclado),
// así que el input nativo debajo sería un segundo control redundante
// para un lector de pantalla si también quedara en el árbol.
const ocultoVisualmente = {
  position: "absolute", width: 1, height: 1, padding: 0, margin: -1,
  overflow: "hidden", clip: "rect(0,0,0,0)", whiteSpace: "nowrap", border: 0,
};

// ─── Formato defensivo (reporte 189d - bug real encontrado en la prueba
// del usuario: "NaN MB · Invalid Date" en la lista, causado por un
// bundle viejo del navegador leyendo campos de una forma de respuesta
// que ya había cambiado - ver R0). Ninguna de estas funciones debe
// devolver jamás "NaN" ni "Invalid Date": ante un dato ausente o
// inválido devuelven null, y unir() se encarga de omitirlo del todo en
// vez de mostrar un hueco o un placeholder confuso. ────────────────────

function unir(...partes) {
  return partes.filter(Boolean).join(" · ");
}

function formatoBytes(n) {
  if (typeof n !== "number" || !Number.isFinite(n)) return null;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatoFecha(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  try {
    return d.toLocaleDateString("es-MX", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return null;
  }
}

// "Presentada el dd/mm/aaaa" (pedido explícito R2) - formato numérico
// fijo, distinto de formatoFecha() de arriba (que usa mes abreviado en
// español, para la fecha de SUBIDA de cada documento).
function formatoFechaCorta(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${dd}/${mm}/${d.getFullYear()}`;
}

function formatoMoneda(n) {
  if (typeof n !== "number" || !Number.isFinite(n)) return null;
  return new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" }).format(n);
}

function etiquetaTipo(datos) {
  const base = ETIQUETA_TIPO_DECLARACION[datos?.tipo_declaracion] || datos?.tipo_declaracion;
  if (!base) return null;
  return datos.tipo_declaracion === "complementaria" && datos.numero_complementaria != null
    ? `${base} ${datos.numero_complementaria}`
    : base;
}

// Caso 2013 (pedido explícito R2): si el acuse trae cantidad a cargo en
// vez de saldo a favor, se muestra "A cargo: $X" - NUNCA "Saldo a favor: —".
function etiquetaSaldoOCargo(saldoAFavor, cantidadACargo) {
  const saldo = formatoMoneda(saldoAFavor);
  if (saldo) return `Saldo a favor: ${saldo}`;
  const cargo = formatoMoneda(cantidadACargo);
  if (cargo) return `A cargo: ${cargo}`;
  return null;
}

function validarArchivoCliente(archivo) {
  if (archivo.type !== "application/pdf" && !archivo.name.toLowerCase().endsWith(".pdf")) {
    return "Solo se aceptan archivos PDF";
  }
  if (archivo.size > MAX_MB * 1024 * 1024) return `El archivo no debe exceder ${MAX_MB}MB`;
  return null;
}

export default function DeclaracionesAnualesModal({ emisor, onCerrar }) {
  const toast = useToast();
  const overlayRef = useRef(null);
  const primerCampoRef = useRef(null);
  const elementoQueAbrioRef = useRef(null);
  // 188/M1: id (no el nodo DOM) del elemento que tenia el foco cuando se
  // disparo la confirmacion, para devolver el foco ahi en "Seguir
  // editando" - generico (cualquier elemento con id), sigue funcionando
  // igual aunque ya no haya campos de formulario fijos.
  const idCampoEnfocadoRef = useRef(null);
  // 188/M1: cual de las 4 vias de cierre disparo la confirmacion -
  // "cerrar" (fondo/Esc/X, cierra TODO el modal) vs "cancelar" (el
  // boton Cancelar, solo vuelve a la lista). Descartar() se comporta
  // distinto segun cual fue.
  const accionPendienteRef = useRef(null);

  const [documentos, setDocumentos] = useState(null); // null = cargando; lista de DECLARACIONES (reporte 189), cada una con .documentos anidados
  const [errorLista, setErrorLista] = useState(null);
  const [mostrandoForm, setMostrandoForm] = useState(false);
  const [mostrandoConfirmacion, setMostrandoConfirmacion] = useState(false);

  // ─── Borrar declaración completa (reporte 189b, F3) ────────────────────
  const [declaracionABorrar, setDeclaracionABorrar] = useState(null);
  const [borrandoDeclaracion, setBorrandoDeclaracion] = useState(false);
  const idBotonBorrarDeclRef = useRef(null);

  // ─── Subida múltiple (reporte 189d, R2) ─────────────────────────────────
  // archivos: [{ id, file, estado: 'analizando'|'valido'|'duplicado'|
  // 'rechazado', analisis (respuesta de /analizar o null), mensaje
  // (motivo del rechazo/duplicado, o null) }]. La cola de análisis corre
  // SECUENCIAL (nunca en paralelo) via colaAnalisisRef - cada PDF ya usa
  // un proceso aparte en el servidor con hasta 5s de margen
  // (declaraciones_pdf.py); analizar varios a la vez multiplicaría esa
  // carga sin necesidad.
  const [archivos, setArchivos] = useState([]);
  const [arrastrando, setArrastrando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const inputArchivosRef = useRef(null);
  const colaAnalisisRef = useRef(Promise.resolve());
  // 189d3 - montadoRef guarda si el componente SIGUE en el DOM; el
  // analisis de un archivo puede seguir en vuelo cuando el modal se
  // cierra (unmount) - sin esto, la respuesta que llega despues
  // dispararia setArchivos() sobre un componente ya desmontado (warning
  // real de React en consola). abortControllerRef permite ademas
  // CANCELAR la peticion HTTP de verdad (no solo ignorar su resultado) -
  // ver cancelarAnalisisEnCurso() abajo.
  const montadoRef = useRef(true);
  const abortControllerRef = useRef(null);

  // "Sucio" si hay al menos un acuse VÁLIDO sin guardar, O uno que
  // TODAVÍA se está analizando (reporte 189d3 - hallazgo real de la
  // corrida E2E del usuario: un clic en el fondo mientras el PDF seguía
  // en análisis cerraba el modal sin preguntar y perdía el archivo,
  // porque "analizando" no contaba como sucio). Rechazados y duplicados
  // siguen sin contar - ya se sabe que no hay nada que guardar de ellos.
  const hayAlgoQuePerder = archivos.some(a => a.estado === "valido" || a.estado === "analizando");
  const estaSucio = mostrandoForm && hayAlgoQuePerder;
  const numValidos = archivos.filter(a => a.estado === "valido").length;

  // Cancela la petición /analizar en vuelo (si hay una) - se llama antes
  // de vaciar la cola (Cancelar/Descartar) y en el cleanup de
  // desmontaje. abort() nunca lanza si ya no hay nada que cancelar.
  const cancelarAnalisisEnCurso = () => {
    abortControllerRef.current?.abort();
  };

  // ─── Carga inicial ──────────────────────────────────────────────────────
  const cargar = async () => {
    setErrorLista(null);
    try {
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.id}/declaraciones-anuales/documentos`);
      const data = await res.json().catch(() => ([]));
      if (!res.ok) throw new Error(detalleError(data, res));
      setDocumentos(data);
    } catch (e) {
      setErrorLista(e.message);
    }
  };
  useEffect(() => { cargar(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  // ─── 188/M1: cierre con guardia de cambios sin guardar ─────────────────
  const solicitarCierre = (accion) => {
    if (guardando || borrandoDeclaracion) return;
    // La confirmación de borrar declaración TAMBIÉN intercepta las 4 vías
    // de cierre - cerrar el modal completo aquí perdería silenciosamente
    // el contexto de qué se iba a borrar. Cancela SOLO esa confirmación.
    if (declaracionABorrar) { setDeclaracionABorrar(null); return; }
    if (estaSucio) {
      idCampoEnfocadoRef.current = document.activeElement?.id || null;
      accionPendienteRef.current = accion;
      setMostrandoConfirmacion(true);
      return;
    }
    if (accion === "cancelar") {
      cancelarAnalisisEnCurso();
      setMostrandoForm(false);
      setArchivos([]);
    } else {
      cancelarAnalisisEnCurso();
      onCerrar();
    }
  };

  const seguirEditando = () => setMostrandoConfirmacion(false);

  const descartar = () => {
    setMostrandoConfirmacion(false);
    cancelarAnalisisEnCurso();
    if (accionPendienteRef.current === "cancelar") {
      setArchivos([]);
      setMostrandoForm(false);
    } else {
      onCerrar();
    }
  };

  // Devuelve el foco al elemento donde estaba (por id).
  useEffect(() => {
    if (!mostrandoConfirmacion && mostrandoForm && idCampoEnfocadoRef.current) {
      document.getElementById(idCampoEnfocadoRef.current)?.focus();
      idCampoEnfocadoRef.current = null;
    }
  }, [mostrandoConfirmacion, mostrandoForm]);

  // Foco por defecto en "Seguir editando" al abrir la confirmacion.
  useEffect(() => {
    if (mostrandoConfirmacion) {
      document.getElementById("da-confirmar-seguir-editando")?.focus();
    }
  }, [mostrandoConfirmacion]);

  // Mismo patrón de foco que la guardia de cambios (F3): al abrir, foco
  // en la opción SEGURA por defecto (Cancelar); al cerrar (cancelar), el
  // foco vuelve al botón "Borrar" que la abrió.
  useEffect(() => {
    if (declaracionABorrar) {
      document.getElementById("da-confirmar-borrar-decl-cancelar")?.focus();
    } else if (idBotonBorrarDeclRef.current) {
      document.getElementById(idBotonBorrarDeclRef.current)?.focus();
      idBotonBorrarDeclRef.current = null;
    }
  }, [declaracionABorrar]);

  // ─── Accesibilidad: captura de apertura + foco inicial + retorno ───────
  useEffect(() => {
    elementoQueAbrioRef.current = document.activeElement;
    primerCampoRef.current?.focus();
    return () => {
      elementoQueAbrioRef.current?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 189d3 - limpieza al desmontar: marca montadoRef=false (para que
  // cualquier setArchivos() de una respuesta que llegue tarde se
  // ignore, ver analizarUno) y cancela la petición /analizar en vuelo,
  // si la hay - red de seguridad final para cualquier vía de cierre que
  // desmonte el componente sin haber pasado por cancelarAnalisisEnCurso()
  // explícitamente arriba.
  useEffect(() => {
    return () => {
      montadoRef.current = false;
      abortControllerRef.current?.abort();
    };
  }, []);

  // ─── Accesibilidad: foco atrapado + Esc ────────────────────────────────
  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        if (mostrandoConfirmacion) { seguirEditando(); return; }
        if (declaracionABorrar) { setDeclaracionABorrar(null); return; }
        solicitarCierre("cerrar");
        return;
      }
      if (e.key !== "Tab" || !overlayRef.current) return;
      const focusables = overlayRef.current.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const primero = focusables[0];
      const ultimo = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === primero) {
        e.preventDefault();
        ultimo.focus();
      } else if (!e.shiftKey && document.activeElement === ultimo) {
        e.preventDefault();
        primero.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mostrandoConfirmacion, guardando, estaSucio, declaracionABorrar, borrandoDeclaracion]);

  // ─── Analizar (reporte 189, multi-archivo desde 189d) ──────────────────
  // actualizarArchivo: único punto que llama setArchivos() para un
  // archivo de la cola - SIEMPRE revisa montadoRef primero (189d3: sin
  // esto, una respuesta de /analizar que llega DESPUÉS de que el modal
  // ya se cerró dispara "Can't perform a React state update on an
  // unmounted component" en consola).
  const actualizarArchivo = (id, cambios) => {
    if (!montadoRef.current) return;
    setArchivos(prev => prev.map(a => a.id === id ? { ...a, ...cambios } : a));
  };

  const analizarUno = async (entry) => {
    const errorCliente = validarArchivoCliente(entry.file);
    if (errorCliente) {
      actualizarArchivo(entry.id, { estado: "rechazado", mensaje: errorCliente });
      return;
    }
    if (!montadoRef.current) return; // el modal ya se cerró - no arrancar una petición nueva
    const controller = new AbortController();
    abortControllerRef.current = controller;
    try {
      const body = new FormData();
      body.append("archivo", entry.file);
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.id}/declaraciones-anuales/analizar`, {
        method: "POST",
        body,
        signal: controller.signal,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        // Cubre NO_RECONOCIDO (422, reporte 189d R1) y cualquier otro
        // error HTTP - el detalle del servidor ES el motivo a mostrar.
        actualizarArchivo(entry.id, { estado: "rechazado", mensaje: detalleError(data, res) });
        return;
      }
      if (!data.puede_guardar) {
        // Cubre opinión de cumplimiento, RFC ajeno, número de operación
        // duplicado, o ejercicio no determinado - todos vienen como 200
        // OK con puede_guardar=false (ver _evaluar_analisis en main.py).
        const esDuplicado = data.mensaje === MENSAJE_DUPLICADO_SERVIDOR;
        actualizarArchivo(entry.id, {
          estado: esDuplicado ? "duplicado" : "rechazado",
          mensaje: esDuplicado ? "Ya está registrado" : data.mensaje,
          analisis: data,
        });
        return;
      }
      actualizarArchivo(entry.id, { estado: "valido", analisis: data, mensaje: null });
    } catch (e) {
      // AbortError = cancelado a propósito (cerramos/descartamos antes
      // de que respondiera) - NUNCA un error real que mostrar (189d3).
      if (e.name === "AbortError") return;
      // Cualquier otro fallo de RED/lectura (no una clasificación válida
      // del servidor) - "no se pudo leer" (uno de los 4 motivos pedidos
      // en R2).
      actualizarArchivo(entry.id, { estado: "rechazado", mensaje: `No se pudo leer: ${e.message}` });
    }
  };

  const agregarArchivos = (fileList) => {
    const nuevos = Array.from(fileList || []).map(file => ({
      id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
      file, estado: "analizando", analisis: null, mensaje: null,
    }));
    if (nuevos.length === 0) return;
    setArchivos(prev => [...prev, ...nuevos]);
    // Encadenado sobre la MISMA promesa (colaAnalisisRef) para que dos
    // llamadas seguidas (ej. el usuario suelta un lote, luego otro antes
    // de que termine el primero) tambien queden en fila, nunca se
    // encimen.
    colaAnalisisRef.current = nuevos.reduce(
      (promesaAnterior, entry) => promesaAnterior.then(() => analizarUno(entry)),
      colaAnalisisRef.current,
    );
  };

  const quitarArchivo = (id) => setArchivos(prev => prev.filter(a => a.id !== id));

  const onDrop = (e) => {
    e.preventDefault();
    setArrastrando(false);
    if (guardando) return;
    agregarArchivos(e.dataTransfer.files);
  };

  // ─── Guardar (reporte 189d, R2) - guarda cada VÁLIDO uno por uno; un
  // fallo no detiene a los demás (pedido explícito). ──────────────────────
  const guardarTodos = async () => {
    setGuardando(true);
    const validos = archivos.filter(a => a.estado === "valido");
    let exitos = 0;
    for (const entry of validos) {
      try {
        const body = new FormData();
        body.append("archivo", entry.file);
        const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.id}/declaraciones-anuales/documentos`, {
          method: "POST",
          body, // fetchAuth NO debe forzar Content-Type json aqui - FormData fija su propio boundary
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(detalleError(data, res));
        exitos += 1;
        setArchivos(prev => prev.filter(a => a.id !== entry.id));
      } catch (e) {
        setArchivos(prev => prev.map(a => a.id === entry.id ? { ...a, estado: "rechazado", mensaje: `No se pudo guardar: ${e.message}` } : a));
      }
    }
    setGuardando(false);
    if (exitos > 0) {
      toast(exitos === 1 ? "1 acuse guardado" : `${exitos} acuses guardados`, "success");
      cargar();
    }
    if (exitos === validos.length && validos.length > 0) {
      // Todo lo que se intento guardar salio bien - ya no queda nada
      // pendiente en la cola, vuelve a la lista (mismo criterio que 188:
      // tras un exito total, cerrar ya no debe pedir confirmacion).
      setMostrandoForm(false);
      setArchivos([]);
    }
  };

  const descargar = async (doc) => {
    try {
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.id}/declaraciones-anuales/documentos/${doc.id}/descarga`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(detalleError(data, res));
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = doc.nombre_archivo_original || "acuse.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast(`No se pudo descargar: ${e.message}`, "error");
    }
  };

  // ─── Borrar declaración completa (reporte 189b, F3) - ÚNICA acción de
  // borrado por tarjeta desde 189d (R2): el "Borrar" por documento se
  // quitó del todo (ver JSX) - mientras una declaración tenga un solo
  // documento (el caso normal hoy: el flujo de subida crea 1 documento
  // por declaración), borrar la declaración completa YA borra ese único
  // acuse también (main.py, borrar_declaracion_anual). ───────────────────
  const pedirBorrarDeclaracion = (decl) => {
    idBotonBorrarDeclRef.current = `da-borrar-decl-${decl.id}`;
    setDeclaracionABorrar(decl);
  };

  const confirmarBorrarDeclaracion = async () => {
    if (!declaracionABorrar) return;
    setBorrandoDeclaracion(true);
    try {
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.id}/declaraciones-anuales/${declaracionABorrar.id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) {
        const data = await res.json().catch(() => ({}));
        throw new Error(detalleError(data, res));
      }
      toast(`Declaración ${declaracionABorrar.ejercicio} eliminada`, "success");
      setDeclaracionABorrar(null);
      cargar();
    } catch (e) {
      toast(`No se pudo borrar la declaración: ${e.message}`, "error");
    } finally {
      setBorrandoDeclaracion(false);
    }
  };

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="declaraciones-modal-titulo"
      style={{
        position: "fixed", inset: 0, background: "rgba(3,6,18,.5)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 120, padding: 12, boxSizing: "border-box",
      }}
      onClick={(e) => { if (e.target === overlayRef.current) solicitarCierre("cerrar"); }}
    >
      <Card
        style={{
          width: 480, maxWidth: "calc(100vw - 24px)", maxHeight: "calc(100dvh - 24px)",
          display: "flex", flexDirection: "column", overflow: "hidden", padding: 0,
        }}
      >
        <div style={{ padding: "16px 20px 12px", borderBottom: `1px solid ${C.border}`, display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexShrink: 0 }}>
          <div>
            <div id="declaraciones-modal-titulo" style={{ fontSize: 16, fontWeight: 700, color: C.text }}>Declaraciones anuales</div>
            <div style={{ fontSize: 12, color: C.textMuted, fontFamily: "monospace", marginTop: 2 }}>{emisor.rfc}</div>
          </div>
          <button
            ref={!mostrandoForm ? primerCampoRef : undefined}
            type="button"
            aria-label="Cerrar"
            disabled={guardando}
            onClick={() => solicitarCierre("cerrar")}
            style={{ background: "none", border: "none", fontSize: 20, lineHeight: 1, color: C.textMuted, cursor: guardando ? "not-allowed" : "pointer", opacity: guardando ? .5 : 1, padding: 4, minWidth: 44, minHeight: 44 }}
          >
            ×
          </button>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "14px 20px" }}>
          {mostrandoConfirmacion ? (
            // 188/M1: confirmacion DENTRO del modal (nunca window.confirm).
            <div role="alertdialog" aria-modal="true" aria-labelledby="da-confirmar-titulo" aria-describedby="da-confirmar-texto">
              <div id="da-confirmar-titulo" style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 8 }}>
                Tienes cambios sin guardar
              </div>
              <div id="da-confirmar-texto" style={{ fontSize: 13, color: C.textSec, marginBottom: 18 }}>
                ¿Descartarlos?
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  id="da-confirmar-seguir-editando"
                  type="button"
                  onClick={seguirEditando}
                  style={{ flex: 1, minHeight: 44, borderRadius: 8, padding: "10px 18px", fontSize: 13, fontWeight: 600, cursor: "pointer", border: "none", background: C.primary, color: C.accent }}
                >
                  Seguir editando
                </button>
                <Btn type="button" variant="secondary" style={{ minHeight: 44, color: C.danger, borderColor: C.danger }} onClick={descartar}>
                  Descartar
                </Btn>
              </div>
            </div>
          ) : declaracionABorrar ? (
            // F3: mismo patrón que la confirmación de cambios sin guardar.
            <div role="alertdialog" aria-modal="true" aria-labelledby="da-confirmar-borrar-decl-titulo" aria-describedby="da-confirmar-borrar-decl-texto">
              <div id="da-confirmar-borrar-decl-titulo" style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 8 }}>
                Borrar declaración
              </div>
              <div id="da-confirmar-borrar-decl-texto" style={{ fontSize: 13, color: C.textSec, marginBottom: 18 }}>
                Se borrarán la declaración de ejercicio {declaracionABorrar.ejercicio} y sus{" "}
                {declaracionABorrar.documentos.length}{" "}
                {declaracionABorrar.documentos.length === 1 ? "documento" : "documentos"}. Esta acción no se puede deshacer.
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  id="da-confirmar-borrar-decl-cancelar"
                  type="button"
                  disabled={borrandoDeclaracion}
                  onClick={() => setDeclaracionABorrar(null)}
                  style={{ flex: 1, minHeight: 44, borderRadius: 8, padding: "10px 18px", fontSize: 13, fontWeight: 600, cursor: borrandoDeclaracion ? "not-allowed" : "pointer", border: "none", background: C.primary, color: C.accent, opacity: borrandoDeclaracion ? .6 : 1 }}
                >
                  Cancelar
                </button>
                <Btn type="button" variant="secondary" disabled={borrandoDeclaracion} style={{ minHeight: 44, color: C.danger, borderColor: C.danger }} onClick={confirmarBorrarDeclaracion}>
                  {borrandoDeclaracion ? "Borrando…" : "Borrar declaración"}
                </Btn>
              </div>
            </div>
          ) : !mostrandoForm ? (
            <>
              <Btn type="button" style={{ width: "100%", marginBottom: 14, minHeight: 44 }} onClick={() => setMostrandoForm(true)}>
                Subir acuses
              </Btn>

              {documentos === null && !errorLista && (
                <div style={{ fontSize: 13, color: C.textMuted, textAlign: "center", padding: "20px 0" }}>Cargando…</div>
              )}
              {errorLista && (
                <div role="alert" aria-live="assertive" style={{ fontSize: 12, color: C.danger, background: C.dangerSoft, borderRadius: 6, padding: "8px 10px", marginBottom: 10 }}>
                  ⚠ No se pudo cargar: {errorLista}
                </div>
              )}
              {documentos !== null && documentos.length === 0 && !errorLista && (
                <div style={{ fontSize: 13, color: C.textMuted, textAlign: "center", padding: "20px 0" }}>
                  Aún no has subido declaraciones.
                </div>
              )}
              {/* Lista por DECLARACIÓN (reporte 189) - ya viene agrupada
                  del servidor, ordenada ejercicio desc. Formato defensivo
                  (189d): cada pieza (tipo/fecha/saldo) se omite si falta,
                  nunca "NaN" ni "Invalid Date" ni "Saldo a favor: —". */}
              {documentos?.map(decl => {
                const lineaSecundaria = unir(
                  formatoFechaCorta(decl.fecha_presentacion) ? `Presentada el ${formatoFechaCorta(decl.fecha_presentacion)}` : null,
                  etiquetaSaldoOCargo(decl.saldo_a_favor, decl.cantidad_a_cargo),
                );
                return (
                  <div key={decl.id} style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px", marginBottom: 8 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>
                        {unir(`Ejercicio ${decl.ejercicio}`, etiquetaTipo(decl))}
                      </div>
                      {decl.origen === "manual" && (
                        <span style={{ fontSize: 10, color: C.textMuted, border: `1px solid ${C.border}`, borderRadius: 20, padding: "1px 7px", flexShrink: 0 }}>
                          sin verificar
                        </span>
                      )}
                    </div>
                    {lineaSecundaria && (
                      <div style={{ fontSize: 12, color: C.textSec, marginBottom: 8 }}>{lineaSecundaria}</div>
                    )}
                    {/* Jerarquía visual (pedido explícito R2): el
                        contenido de arriba es lo principal; "Descargar
                        acuse" es secundario (dentro de cada documento);
                        "Borrar" es terciario, AL FINAL de la tarjeta, sin
                        relleno rojo ni subrayado (el rojo solo vive en la
                        confirmación). Única acción de borrado por
                        tarjeta - el "Borrar" por documento se quitó. */}
                    {decl.documentos.map(doc => {
                      const metaDoc = unir(formatoBytes(doc.tamano_bytes), formatoFecha(doc.creado_en));
                      return (
                        <div key={doc.id} style={{ background: C.surface, borderRadius: 6, padding: "6px 8px", marginBottom: 6 }}>
                          <div style={{ fontSize: 11, color: C.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={doc.nombre_archivo_original}>
                            {doc.nombre_archivo_original}
                          </div>
                          {metaDoc && <div style={{ fontSize: 10, color: C.textMuted, marginBottom: 6 }}>{metaDoc}</div>}
                          <Btn type="button" variant="secondary" style={{ width: "100%", fontSize: 11, padding: "5px 8px", minHeight: 36 }} onClick={() => descargar(doc)}>
                            Descargar acuse
                          </Btn>
                        </div>
                      );
                    })}
                    <button
                      id={`da-borrar-decl-${decl.id}`}
                      type="button"
                      onClick={() => pedirBorrarDeclaracion(decl)}
                      style={{ fontSize: 11, color: C.textMuted, background: "none", border: "none", padding: "10px 0 0", marginTop: 2, cursor: "pointer", minHeight: 44, display: "flex", alignItems: "center" }}
                    >
                      Borrar
                    </button>
                  </div>
                );
              })}
            </>
          ) : (
            <div>
              {/* Dropzone multi-archivo (reporte 189d, R2; CORREGIDO en
                  189d2 - hallazgo real de axe: "nested-interactive"
                  serious, porque la version anterior ponia el <input
                  type="file"> (control nativo interactivo) DENTRO de un
                  DIV con role="button" (otro control interactivo) -
                  aria-hidden/tabIndex=-1 en el input NO evitaban la
                  violacion, un control interactivo nunca debe anidarse
                  dentro de otro sin importar esos atributos.
                  Corregido con el patron recomendado: la region de
                  arrastrar y soltar ya NO es un control (sin role,
                  sin tabIndex, sin manejo manual de Enter/Espacio) -
                  solo texto + los manejadores de arrastre, que son
                  puramente de mouse/mismo elemento, nunca la unica via
                  (el boton de abajo siempre alcanza el mismo resultado
                  por teclado). Un solo <button> real "Seleccionar PDF"
                  abre el selector - un <button> nativo YA es operable
                  con Enter/Espacio por el navegador, sin JS a mano. El
                  <input> real sigue oculto visualmente, fuera de
                  tabulacion y sin anidarse en ningun control. */}
              <div
                onDrop={onDrop}
                onDragOver={e => { e.preventDefault(); if (!guardando) setArrastrando(true); }}
                onDragLeave={() => setArrastrando(false)}
                style={{
                  border: `2px dashed ${arrastrando ? C.accent : C.border}`, borderRadius: 10,
                  padding: "22px 14px", textAlign: "center",
                  background: arrastrando ? C.accentSoft : "transparent",
                  transition: "all .15s", marginBottom: 14,
                  opacity: guardando ? .6 : 1,
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 600, color: C.text, marginBottom: 10 }}>
                  Arrastra tus acuses aquí o
                </div>
                <button
                  type="button"
                  onClick={() => inputArchivosRef.current?.click()}
                  disabled={guardando}
                  style={{
                    minHeight: 44, minWidth: 44, borderRadius: 8,
                    padding: "10px 18px", fontSize: 13, fontWeight: 600,
                    cursor: guardando ? "not-allowed" : "pointer",
                    background: "transparent", color: C.textSec, border: `1px solid ${C.border}`,
                  }}
                >
                  Seleccionar PDF
                </button>
                <div style={{ fontSize: 11, color: C.textMuted, marginTop: 8 }}>
                  PDF · máx. {MAX_MB}MB cada uno · puedes elegir varios
                </div>
                <input
                  ref={inputArchivosRef}
                  id="da-archivos"
                  type="file"
                  accept="application/pdf,.pdf"
                  multiple
                  disabled={guardando}
                  aria-hidden="true"
                  tabIndex={-1}
                  onChange={e => { agregarArchivos(e.target.files); e.target.value = ""; }}
                  style={ocultoVisualmente}
                />
              </div>

              {/* Resultado del análisis por archivo (reporte 189d) -
                  aria-live para que un lector de pantalla anuncie cada
                  estado sin que el usuario tenga que navegar a buscarlo. */}
              {archivos.length > 0 && (
                <ul aria-live="polite" style={{ listStyle: "none", padding: 0, margin: "0 0 14px" }}>
                  {archivos.map(a => (
                    <li key={a.id} style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px", marginBottom: 6 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{ fontSize: 11, color: C.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={a.file.name}>
                            {a.file.name}
                          </div>
                          {a.estado === "analizando" && (
                            <div style={{ fontSize: 12, color: C.textMuted }}>Analizando…</div>
                          )}
                          {a.estado === "valido" && a.analisis?.extraido && (
                            <div style={{ fontSize: 12, color: C.text }}>
                              {unir(`Ejercicio ${a.analisis.extraido.ejercicio}`, etiquetaTipo(a.analisis.extraido))}
                              <br />
                              {unir(
                                formatoFechaCorta(a.analisis.extraido.fecha_presentacion)
                                  ? `Presentada el ${formatoFechaCorta(a.analisis.extraido.fecha_presentacion)}`
                                  : null,
                                etiquetaSaldoOCargo(a.analisis.extraido.saldo_a_favor, a.analisis.extraido.cantidad_a_cargo),
                              ) || "Válido"}
                            </div>
                          )}
                          {a.estado === "duplicado" && (
                            <div style={{ fontSize: 12, color: C.warn }}>⚠ {a.mensaje}</div>
                          )}
                          {a.estado === "rechazado" && (
                            <div style={{ fontSize: 12, color: C.danger }}>⚠ {a.mensaje}</div>
                          )}
                        </div>
                        <button
                          type="button"
                          id={`da-quitar-${a.id}`}
                          onClick={() => quitarArchivo(a.id)}
                          disabled={guardando}
                          aria-label={`Quitar ${a.file.name} de la selección`}
                          style={{ fontSize: 11, color: C.textMuted, background: "none", border: `1px solid ${C.border}`, borderRadius: 6, padding: "8px 10px", cursor: guardando ? "not-allowed" : "pointer", minHeight: 44, minWidth: 44, flexShrink: 0 }}
                        >
                          Quitar
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              <div style={{ display: "flex", gap: 8 }}>
                <Btn type="button" disabled={guardando || numValidos === 0} style={{ flex: 1, minHeight: 44 }} onClick={guardarTodos}>
                  {guardando ? "Guardando…" : `Guardar ${numValidos} ${numValidos === 1 ? "acuse" : "acuses"}`}
                </Btn>
                <Btn type="button" variant="secondary" style={{ minHeight: 44 }} disabled={guardando} onClick={() => solicitarCierre("cancelar")}>
                  Cancelar
                </Btn>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
