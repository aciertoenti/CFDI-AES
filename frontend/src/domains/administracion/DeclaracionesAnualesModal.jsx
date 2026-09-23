import { useEffect, useRef, useState } from "react";
import { useToast } from "../../shared/layout/ToastProvider";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Btn, Card } from "../../shared/components/atoms";
import SelectorArchivo from "../../shared/components/SelectorArchivo";
import { C, detalleError } from "../../shared/utils/format";

// Declaraciones anuales - modal de documentos (Parte B, 22 sep 2026;
// validación por CONTENIDO del PDF, reporte 189, 23 sep 2026).
//
// Reporte 189 - motivo real: antes se guardaba el ejercicio/tipo que el
// usuario elegía A MANO, sin leer el PDF - una prueba real guardó un
// acuse de 2013 como si fuera 2025, y una opinión de cumplimiento como
// si fuera una declaración. Ahora, al elegir el archivo, se analiza
// automáticamente (POST .../analizar, solo lectura) y se muestra una
// tarjeta de confirmación con lo detectado ANTES de guardar - ejercicio
// y tipo de declaración quedan NO editables cuando se extrajeron del
// documento (el servidor los vuelve a extraer al guardar de todas
// formas, nunca confía en lo que mande el cliente).
//
// Accesibilidad (WCAG 2.2 AA, pedido explicito - los modales existentes
// del proyecto, EditarEmisorModal/EliminarEmisorConfirm/ReemplazarCsdForm,
// NO implementan foco atrapado/Esc/aria-modal, asi que esto es NUEVO en
// el repo, no una copia de un patron ya probado): foco atrapado dentro
// del dialog, Escape cierra, el foco vuelve al boton que abrio el modal
// al cerrar, role="dialog" + aria-modal, aria-live en errores Y en el
// resultado del análisis (el usuario con lector de pantalla se entera
// de la clasificación sin tener que navegar a buscarla).
//
// Guardia de cambios sin guardar (corregido 22 sep 2026 - problema real
// encontrado en prueba manual: clic fuera del modal lo cerraba sin aviso
// y se perdia lo capturado): las 4 vias de cierre (fondo/Esc/X/Cancelar)
// pasan por solicitarCierre(), que intercepta con una confirmacion
// DENTRO del modal (role="alertdialog", nunca window.confirm) si el
// formulario esta "sucio" (algun campo distinto de FORM_INICIAL, o un
// archivo seleccionado). Ver seguirEditando()/descartar() abajo.

// Mismo limite que declaraciones_storage.EJERCICIO_MINIMO (backend) -
// duplicado a proposito (no hay endpoint dedicado solo para exponer este
// rango, evita una llamada de red extra para un dato estatico que rara
// vez cambia). Si el backend cambia este valor, actualizar aqui tambien.
// CORREGIDO 22 sep 2026 (reporte 185/C2): existen acuses reales del
// titular desde 2013 - 2014 los rechazaba. 2000 da margen amplio, mismo
// valor y mismo motivo que el backend.
const EJERCICIO_MINIMO = 2000;
const EJERCICIO_MAXIMO = new Date().getFullYear() - 1;
const AÑOS_VALIDOS = Array.from(
  { length: EJERCICIO_MAXIMO - EJERCICIO_MINIMO + 1 },
  (_, i) => EJERCICIO_MAXIMO - i,
);

const MAX_MB = 5; // mismo default que MAX_DECLARACION_PDF_BYTES del backend

const TIPOS_DOCUMENTO = [
  { value: "declaracion", label: "Declaración" },
  { value: "acuse", label: "Acuse" },
  { value: "comprobante_pago", label: "Comprobante de pago" },
];

// Extraido a constante (antes vivia inline, duplicado entre el useState
// inicial y el reset post-exito) - reutilizado tambien por el chequeo de
// "sucio" (M1) y por descartar() al confirmar Cancelar.
const FORM_INICIAL = {
  ejercicio: EJERCICIO_MAXIMO,
  tipo_declaracion: "normal",
  numero_complementaria: "",
  tipo_documento: "declaracion",
  archivo: null,
};

const inputStyle = {
  width: "100%", border: `1px solid ${C.border}`, borderRadius: 8,
  padding: "8px 11px", fontSize: 13, color: C.text, background: "#fff",
  boxSizing: "border-box",
};
const inputStyleSoloLectura = {
  ...inputStyle, background: C.surface, color: C.textSec, cursor: "not-allowed",
};
const labelStyle = { fontSize: 12, color: C.textSec, display: "block", marginBottom: 3 };

function formatoBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatoFecha(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("es-MX", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

function formatoFechaHora(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("es-MX", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function formatoMoneda(n) {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" }).format(n);
}

const ETIQUETA_TIPO_DECLARACION = { normal: "Normal", complementaria: "Complementaria" };

export default function DeclaracionesAnualesModal({ emisor, onCerrar }) {
  const toast = useToast();
  const overlayRef = useRef(null);
  const primerCampoRef = useRef(null);
  const elementoQueAbrioRef = useRef(null);
  // M1: id (no el nodo DOM - el formulario se remonta al volver de la
  // confirmacion) del campo que tenia el foco cuando se disparo la
  // confirmacion, para devolver el foco ahi en "Seguir editando".
  const idCampoEnfocadoRef = useRef(null);
  // M1: cual de las 4 vias de cierre disparo la confirmacion -
  // "cerrar" (fondo/Esc/X, cierra TODO el modal) vs "cancelar" (el
  // boton Cancelar del formulario, solo vuelve a la lista). Descartar()
  // se comporta distinto segun cual fue.
  const accionPendienteRef = useRef(null);

  const [documentos, setDocumentos] = useState(null); // null = cargando; ahora es una lista de DECLARACIONES (reporte 189), cada una con .documentos anidados
  const [errorLista, setErrorLista] = useState(null);
  const [mostrandoForm, setMostrandoForm] = useState(false);
  const [mostrandoConfirmacion, setMostrandoConfirmacion] = useState(false);

  // ─── Borrar declaración completa (reporte 189b, F3) ────────────────────
  // declaracionABorrar: la declaración (objeto de la lista, no solo el id -
  // se necesita decl.documentos.length para el texto "y sus N documentos")
  // pendiente de confirmar, o null. Mismo patrón que mostrandoConfirmacion
  // de arriba: reemplaza la lista en vez de superponerse, foco por defecto
  // en la opción SEGURA (Cancelar, no Borrar), y el id del botón que abrió
  // la confirmación se guarda para devolver el foco ahí al cancelar (mismo
  // patrón de idCampoEnfocadoRef, ver abajo).
  const [declaracionABorrar, setDeclaracionABorrar] = useState(null);
  const [borrandoDeclaracion, setBorrandoDeclaracion] = useState(false);
  const idBotonBorrarDeclRef = useRef(null);

  const [form, setForm] = useState({ ...FORM_INICIAL });
  const [subiendo, setSubiendo] = useState(false);
  const [errorForm, setErrorForm] = useState(null);
  const [errorEsDuplicado, setErrorEsDuplicado] = useState(false);

  // ─── Análisis de contenido del PDF (reporte 189) ───────────────────────
  // analizando: cargando la respuesta de /analizar. analisis: el
  // resultado (tipo_detectado, puede_guardar, mensaje, rfc_detectado/
  // rfc_coincide, extraido) o null si aún no se ha analizado nada
  // (formulario recién abierto, sin archivo). errorAnalisis: fallo de
  // RED al llamar /analizar (distinto de "documento no reconocido", que
  // SÍ es una respuesta válida del servidor).
  const [analizando, setAnalizando] = useState(false);
  const [analisis, setAnalisis] = useState(null);
  const [errorAnalisis, setErrorAnalisis] = useState(null);

  // M1: "sucio" solo tiene sentido mientras el formulario esta abierto -
  // en la vista de lista no hay nada que se pueda perder al cerrar.
  const estaSucio = mostrandoForm && (
    form.ejercicio !== FORM_INICIAL.ejercicio ||
    form.tipo_declaracion !== FORM_INICIAL.tipo_declaracion ||
    form.numero_complementaria !== FORM_INICIAL.numero_complementaria ||
    form.tipo_documento !== FORM_INICIAL.tipo_documento ||
    form.archivo !== null
  );

  // Ejercicio/tipo_declaracion vienen del documento (no editables) solo
  // cuando el análisis SÍ pudo extraerlos - en cualquier otro caso
  // (todavía no se analizó, NO_RECONOCIDO, o un rechazo) el usuario los
  // sigue eligiendo a mano, igual que antes de esta tarea.
  const camposExtraidos = analisis?.tipo_detectado === "ACUSE_ANUAL" && analisis?.puede_guardar && !!analisis?.extraido;
  const puedeGuardar = !analizando && (
    !analisis // sin archivo/análisis todavía -> el submit de mas abajo lo bloquea igual (validarArchivoCliente)
    || analisis.tipo_detectado === "NO_RECONOCIDO"
    || (analisis.tipo_detectado === "ACUSE_ANUAL" && analisis.puede_guardar)
  );

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

  // ─── M1: cierre con guardia de cambios sin guardar ─────────────────────
  // Punto UNICO de entrada para las 4 vias de cierre (fondo/Esc/X/Cancelar).
  // Durante una subida, cerrar queda deshabilitado por completo (pedido
  // explicito: "no debe quedar una subida huerfana sin retroalimentacion") -
  // ni siquiera abre la confirmacion, simplemente no hace nada (el boton X
  // y Cancelar ademas quedan visualmente disabled, ver JSX).
  const solicitarCierre = (accion) => {
    if (subiendo || borrandoDeclaracion) return;
    // La confirmación de borrar declaración TAMBIÉN intercepta las 4 vías
    // de cierre (fondo/Esc/X) - igual que la guardia de cambios sin
    // guardar, cerrar el modal completo aquí perdería silenciosamente el
    // contexto de qué se iba a borrar. Cancela SOLO esa confirmación, no
    // cierra el modal.
    if (declaracionABorrar) { setDeclaracionABorrar(null); return; }
    if (estaSucio) {
      idCampoEnfocadoRef.current = document.activeElement?.id || null;
      accionPendienteRef.current = accion;
      setMostrandoConfirmacion(true);
      return;
    }
    if (accion === "cancelar") {
      setMostrandoForm(false);
      setErrorForm(null);
    } else {
      onCerrar();
    }
  };

  const seguirEditando = () => setMostrandoConfirmacion(false);

  const descartar = () => {
    setMostrandoConfirmacion(false);
    if (accionPendienteRef.current === "cancelar") {
      setForm({ ...FORM_INICIAL });
      setAnalisis(null);
      setErrorAnalisis(null);
      setMostrandoForm(false);
      setErrorForm(null);
    } else {
      onCerrar();
    }
  };

  // Devuelve el foco al campo donde estaba (por id, no por referencia al
  // nodo DOM - el formulario se remonta al pasar de confirmacion a form).
  useEffect(() => {
    if (!mostrandoConfirmacion && mostrandoForm && idCampoEnfocadoRef.current) {
      document.getElementById(idCampoEnfocadoRef.current)?.focus();
      idCampoEnfocadoRef.current = null;
    }
  }, [mostrandoConfirmacion, mostrandoForm]);

  // Foco por defecto en "Seguir editando" al abrir la confirmacion
  // (pedido explicito).
  useEffect(() => {
    if (mostrandoConfirmacion) {
      document.getElementById("da-confirmar-seguir-editando")?.focus();
    }
  }, [mostrandoConfirmacion]);

  // Mismo patrón de foco que la guardia de cambios (F3, pedido explícito):
  // al abrir, foco en la opción SEGURA por defecto (Cancelar); al cerrar
  // (cancelar), el foco vuelve al botón "Borrar declaración" que la abrió.
  useEffect(() => {
    if (declaracionABorrar) {
      document.getElementById("da-confirmar-borrar-decl-cancelar")?.focus();
    } else if (idBotonBorrarDeclRef.current) {
      document.getElementById(idBotonBorrarDeclRef.current)?.focus();
      idBotonBorrarDeclRef.current = null;
    }
  }, [declaracionABorrar]);

  // ─── Accesibilidad: captura de apertura + foco inicial + retorno ───────
  // Efecto de MONTAJE/DESMONTAJE unico, deps vacios a proposito - debe
  // correr solo una vez (al abrir/cerrar el modal completo), nunca en
  // cada cambio de mostrandoConfirmacion/subiendo/estaSucio (eso viviria
  // en el efecto de abajo) - si no, "el elemento que abrio esto" se
  // sobreescribiria con cualquier cosa que tuviera el foco en ese
  // momento, y el foco inicial se robaria cada vez que cambia el estado.
  useEffect(() => {
    elementoQueAbrioRef.current = document.activeElement;
    primerCampoRef.current?.focus();
    return () => {
      // Foco de vuelta al boton "Declaraciones anuales" que abrio esto.
      elementoQueAbrioRef.current?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── Accesibilidad: foco atrapado + Esc ────────────────────────────────
  // Efecto SEPARADO del de arriba - este SI debe re-registrarse cuando
  // cambian mostrandoConfirmacion/subiendo/estaSucio, para que el
  // handler de Esc siempre decida con el valor fresco (evita duplicar
  // estado en un ref-mirror solo para esto).
  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        // Esc dentro de la confirmacion equivale a "Seguir editando"
        // (pedido explicito) - NO cierra nada.
        if (mostrandoConfirmacion) { seguirEditando(); return; }
        // Esc dentro de "borrar declaración" equivale a Cancelar (mismo
        // criterio que arriba) - NO borra nada.
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
  }, [mostrandoConfirmacion, subiendo, estaSucio, declaracionABorrar, borrandoDeclaracion]);

  // ─── Analizar (reporte 189) ─────────────────────────────────────────────
  const validarArchivoCliente = (archivo) => {
    if (!archivo) return "Selecciona un archivo";
    if (archivo.type !== "application/pdf" && !archivo.name.toLowerCase().endsWith(".pdf")) {
      return "Solo se aceptan archivos PDF";
    }
    if (archivo.size > MAX_MB * 1024 * 1024) return `El archivo no debe exceder ${MAX_MB}MB`;
    return null;
  };

  // Se dispara automáticamente al elegir un archivo (pedido explícito
  // D4) - SOLO lee/clasifica, nunca guarda nada (POST .../analizar). Si
  // el resultado trae ejercicio/tipo_declaracion extraídos, se reflejan
  // en el formulario (no editables mientras sigan viniendo del
  // documento - ver camposExtraidos arriba).
  const onArchivoSeleccionado = async (archivo) => {
    setAnalisis(null);
    setErrorAnalisis(null);
    setErrorForm(null);
    setErrorEsDuplicado(false);
    setForm(f => ({ ...f, archivo }));

    const errorCliente = validarArchivoCliente(archivo);
    if (errorCliente) { setErrorForm(errorCliente); return; }

    setAnalizando(true);
    try {
      const body = new FormData();
      body.append("archivo", archivo);
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.id}/declaraciones-anuales/analizar`, {
        method: "POST",
        body,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detalleError(data, res));
      setAnalisis(data);
      if (data.tipo_detectado === "ACUSE_ANUAL" && data.puede_guardar && data.extraido) {
        setForm(f => ({
          ...f,
          ejercicio: data.extraido.ejercicio ?? f.ejercicio,
          tipo_declaracion: data.extraido.tipo_declaracion ?? f.tipo_declaracion,
          numero_complementaria: data.extraido.numero_complementaria ?? "",
        }));
      }
    } catch (e) {
      setErrorAnalisis(e.message);
    } finally {
      setAnalizando(false);
    }
  };

  // ─── Subir ──────────────────────────────────────────────────────────────
  const submit = async (e) => {
    e.preventDefault();
    setErrorForm(null);
    setErrorEsDuplicado(false);

    const errorArchivo = validarArchivoCliente(form.archivo);
    if (errorArchivo) { setErrorForm(errorArchivo); return; }
    if (form.tipo_declaracion === "complementaria" && (!form.numero_complementaria || Number(form.numero_complementaria) < 1)) {
      setErrorForm("Indica el número de complementaria (1 o mayor)");
      return;
    }

    setSubiendo(true);
    try {
      const body = new FormData();
      body.append("ejercicio", String(form.ejercicio));
      body.append("tipo_declaracion", form.tipo_declaracion);
      if (form.tipo_declaracion === "complementaria") {
        body.append("numero_complementaria", String(form.numero_complementaria));
      }
      body.append("tipo_documento", form.tipo_documento);
      body.append("archivo", form.archivo);

      // El servidor VUELVE A LEER el PDF aquí (reporte 189) - esto es
      // solo para que el formulario tenga algo consistente que mandar;
      // la fuente de verdad real (ejercicio/tipo/RFC/duplicado) la
      // decide el servidor de nuevo, nunca confía en lo que ya mostró
      // /analizar.
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.id}/declaraciones-anuales/documentos`, {
        method: "POST",
        body, // fetchAuth NO debe forzar Content-Type json aqui - FormData fija su propio boundary
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status === 409) {
          setErrorEsDuplicado(true);
          setErrorForm(detalleError(data, res) || "Este archivo ya estaba guardado");
        } else {
          throw new Error(detalleError(data, res));
        }
        return;
      }
      toast(`Declaración ${form.ejercicio} guardada`, "success");
      setMostrandoForm(false);
      // Tras guardar con exito, el formulario deja de estar "sucio" -
      // vuelve exactamente a FORM_INICIAL (pedido explicito).
      setForm({ ...FORM_INICIAL });
      setAnalisis(null);
      setErrorAnalisis(null);
      cargar();
    } catch (e) {
      // Conserva los datos del formulario (pedido explicito) - no se
      // limpia `form` en el catch, solo se muestra el error.
      setErrorForm(e.message);
    } finally {
      setSubiendo(false);
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
      a.download = doc.nombre_archivo_original || "declaracion.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast(`No se pudo descargar: ${e.message}`, "error");
    }
  };

  const borrar = async (doc) => {
    if (!window.confirm(`¿Borrar "${doc.nombre_archivo_original}"? Esta acción no se puede deshacer.`)) return;
    try {
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.id}/declaraciones-anuales/documentos/${doc.id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) {
        const data = await res.json().catch(() => ({}));
        throw new Error(detalleError(data, res));
      }
      toast("Documento eliminado", "success");
      cargar();
    } catch (e) {
      toast(`No se pudo borrar: ${e.message}`, "error");
    }
  };

  // ─── Borrar declaración completa (reporte 189b, F3) ────────────────────
  // A diferencia de borrar(doc) de arriba (window.confirm, ya existente
  // antes de esta tarea) esta usa la confirmación DENTRO del modal, igual
  // que la guardia de cambios - una acción destructiva mayor (se lleva la
  // declaración Y todos sus documentos) merece el mismo tratamiento
  // accesible, no un window.confirm nativo.
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
            disabled={subiendo}
            onClick={() => solicitarCierre("cerrar")}
            style={{ background: "none", border: "none", fontSize: 20, lineHeight: 1, color: C.textMuted, cursor: subiendo ? "not-allowed" : "pointer", opacity: subiendo ? .5 : 1, padding: 4, minWidth: 44, minHeight: 44 }}
          >
            ×
          </button>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "14px 20px" }}>
          {mostrandoConfirmacion ? (
            // M1: confirmacion DENTRO del modal (nunca window.confirm) -
            // role="alertdialog" (mas preciso que aria-live para un
            // dialogo que pide una decision, se anuncia automaticamente
            // al recibir el foco). Reemplaza al formulario en vez de
            // superponerse - reutiliza el MISMO foco-atrapado de arriba
            // sin cambios, porque los campos del formulario simplemente
            // no estan en el DOM mientras esto se muestra.
            <div role="alertdialog" aria-modal="true" aria-labelledby="da-confirmar-titulo" aria-describedby="da-confirmar-texto">
              <div id="da-confirmar-titulo" style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 8 }}>
                Tienes cambios sin guardar
              </div>
              <div id="da-confirmar-texto" style={{ fontSize: 13, color: C.textSec, marginBottom: 18 }}>
                ¿Descartarlos?
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {/* boton nativo, no <Btn> - Btn no reenvia id/ref al
                    <button> real, y este necesita id para el foco por
                    defecto (ver useEffect de arriba) */}
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
            // F3: mismo patrón que la confirmación de cambios sin guardar
            // de arriba - role="alertdialog", foco por defecto en la
            // opción SEGURA (Cancelar), reemplaza la lista en vez de
            // superponerse.
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
                + Subir declaración
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
                  del servidor, ordenada ejercicio desc. El nombre del
                  archivo del SAT pasa a segundo plano (pedido explícito
                  D4): lo primero que se ve es ejercicio/tipo/fecha/saldo. */}
              {documentos?.map(decl => (
                <div key={decl.id} style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px", marginBottom: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>
                      Ejercicio {decl.ejercicio}
                      <span style={{ fontWeight: 400, color: C.textSec, fontSize: 12 }}>
                        {" · "}{ETIQUETA_TIPO_DECLARACION[decl.tipo_declaracion] || decl.tipo_declaracion}
                        {decl.tipo_declaracion === "complementaria" && decl.numero_complementaria != null ? ` ${decl.numero_complementaria}` : ""}
                      </span>
                    </div>
                    {decl.origen === "manual" && (
                      <span style={{ fontSize: 10, color: C.textMuted, border: `1px solid ${C.border}`, borderRadius: 20, padding: "1px 7px", flexShrink: 0 }}>
                        sin verificar
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 12, color: C.textSec, marginBottom: 8 }}>
                    {formatoFecha(decl.fecha_presentacion)}
                    {" · "}Saldo a favor: {formatoMoneda(decl.saldo_a_favor)}
                  </div>
                  {/* F3: borra la declaración COMPLETA (y todos sus
                      documentos), distinto del "Borrar" de cada documento
                      individual de abajo - id estable por declaracion_id
                      para devolver el foco aquí al cancelar (ver useEffect
                      de arriba). */}
                  <button
                    id={`da-borrar-decl-${decl.id}`}
                    type="button"
                    onClick={() => pedirBorrarDeclaracion(decl)}
                    style={{ fontSize: 11, color: C.danger, background: "none", border: "none", padding: "10px 0", marginBottom: 2, cursor: "pointer", minHeight: 44, textDecoration: "underline", display: "flex", alignItems: "center" }}
                  >
                    Borrar declaración
                  </button>
                  {decl.documentos.map(doc => (
                    <div key={doc.id} style={{ background: C.surface, borderRadius: 6, padding: "6px 8px", marginBottom: 6 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 11, color: C.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {TIPOS_DOCUMENTO.find(t => t.value === doc.tipo_documento)?.label || doc.tipo_documento}
                            {" · "}{doc.nombre_archivo_original}
                          </div>
                          <div style={{ fontSize: 10, color: C.textMuted }}>
                            {formatoBytes(doc.tamano_bytes)}{" · "}{formatoFecha(doc.creado_en)}
                          </div>
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                        <Btn type="button" variant="secondary" style={{ flex: 1, fontSize: 11, padding: "5px 8px", minHeight: 36 }} onClick={() => descargar(doc)}>
                          Descargar
                        </Btn>
                        <Btn type="button" variant="secondary" style={{ flex: 1, fontSize: 11, padding: "5px 8px", minHeight: 36, color: C.danger, borderColor: C.danger }} onClick={() => borrar(doc)}>
                          Borrar
                        </Btn>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </>
          ) : (
            <form onSubmit={submit}>
              <div style={{ marginBottom: 12 }}>
                <label htmlFor="da-ejercicio" style={labelStyle}>Ejercicio</label>
                <select
                  id="da-ejercicio"
                  ref={primerCampoRef}
                  value={form.ejercicio}
                  disabled={camposExtraidos}
                  onChange={e => setForm({ ...form, ejercicio: Number(e.target.value) })}
                  style={camposExtraidos ? inputStyleSoloLectura : inputStyle}
                >
                  {AÑOS_VALIDOS.map(a => <option key={a} value={a}>{a}</option>)}
                </select>
              </div>

              <div style={{ marginBottom: 12 }}>
                <label htmlFor="da-tipo-decl" style={labelStyle}>Tipo de declaración</label>
                <select
                  id="da-tipo-decl"
                  value={form.tipo_declaracion}
                  disabled={camposExtraidos}
                  onChange={e => setForm({ ...form, tipo_declaracion: e.target.value, numero_complementaria: "" })}
                  style={camposExtraidos ? inputStyleSoloLectura : inputStyle}
                >
                  <option value="normal">Normal</option>
                  <option value="complementaria">Complementaria</option>
                </select>
              </div>

              {form.tipo_declaracion === "complementaria" && (
                <div style={{ marginBottom: 12 }}>
                  {/* Sin tope superior (corregido 22 sep 2026, reporte
                      185/C3) - el limite general de Art. 32 CFF (3
                      modificaciones) tiene excepciones reales, un
                      <select> fijo 1-3 las bloqueaba. Input numerico
                      libre, min=1, sin max. */}
                  <label htmlFor="da-numero-comp" style={labelStyle}>Número de complementaria</label>
                  <input
                    id="da-numero-comp"
                    type="number"
                    min="1"
                    step="1"
                    value={form.numero_complementaria}
                    disabled={camposExtraidos}
                    onChange={e => setForm({ ...form, numero_complementaria: e.target.value })}
                    placeholder="Ej. 1"
                    style={camposExtraidos ? inputStyleSoloLectura : inputStyle}
                  />
                </div>
              )}

              <div style={{ marginBottom: 12 }}>
                <label htmlFor="da-tipo-doc" style={labelStyle}>Tipo de documento</label>
                <select
                  id="da-tipo-doc"
                  value={form.tipo_documento}
                  onChange={e => setForm({ ...form, tipo_documento: e.target.value })}
                  style={inputStyle}
                >
                  {TIPOS_DOCUMENTO.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>

              <div style={{ marginBottom: 14 }}>
                <SelectorArchivo
                  id="da-archivo"
                  label={`Archivo PDF (máx. ${MAX_MB}MB)`}
                  accept="application/pdf,.pdf"
                  archivo={form.archivo}
                  onChange={onArchivoSeleccionado}
                  textoBoton="Seleccionar PDF"
                />
              </div>

              {/* Resultado del análisis (reporte 189) - aria-live para
                  que un lector de pantalla lo anuncie sin que el usuario
                  tenga que navegar a buscarlo. */}
              <div aria-live="polite" style={{ marginBottom: form.archivo ? 14 : 0 }}>
                {analizando && (
                  <div style={{ fontSize: 12, color: C.textMuted, display: "flex", alignItems: "center", gap: 6, padding: "8px 0" }}>
                    Analizando documento…
                  </div>
                )}

                {errorAnalisis && !analizando && (
                  <div role="alert" style={{ fontSize: 12, color: C.danger, background: C.dangerSoft, borderRadius: 6, padding: "8px 10px" }}>
                    ⚠ No se pudo analizar el documento: {errorAnalisis}
                  </div>
                )}

                {!analizando && !errorAnalisis && analisis?.tipo_detectado === "OPINION_CUMPLIMIENTO" && (
                  <div role="alert" style={{ fontSize: 12, color: C.warn, background: C.warnSoft, borderRadius: 6, padding: "8px 10px" }}>
                    ⚠ {analisis.mensaje}
                  </div>
                )}

                {!analizando && !errorAnalisis && analisis?.tipo_detectado === "ACUSE_ANUAL" && !analisis.puede_guardar && (
                  <div role="alert" style={{ fontSize: 12, color: C.danger, background: C.dangerSoft, borderRadius: 6, padding: "8px 10px" }}>
                    ⚠ {analisis.mensaje}
                  </div>
                )}

                {!analizando && !errorAnalisis && analisis?.tipo_detectado === "NO_RECONOCIDO" && (
                  <div style={{ fontSize: 12, color: C.textSec, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 6, padding: "8px 10px" }}>
                    No pudimos leer este documento; revisa los datos antes de guardar.
                  </div>
                )}

                {!analizando && !errorAnalisis && analisis?.tipo_detectado === "ACUSE_ANUAL" && analisis.puede_guardar && analisis.extraido && (
                  <div style={{ fontSize: 12, color: C.text, background: C.accentSoft, border: `1px solid ${C.accentBorder}`, borderRadius: 8, padding: "10px 12px" }}>
                    <div style={{ fontWeight: 700, marginBottom: 6 }}>Acuse de declaración anual detectado</div>
                    <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "2px 8px" }}>
                      <span style={{ color: C.textSec }}>Ejercicio:</span><span>{analisis.extraido.ejercicio}</span>
                      <span style={{ color: C.textSec }}>Tipo:</span><span>{ETIQUETA_TIPO_DECLARACION[analisis.extraido.tipo_declaracion] || analisis.extraido.tipo_declaracion}{analisis.extraido.numero_complementaria != null ? ` ${analisis.extraido.numero_complementaria}` : ""}</span>
                      <span style={{ color: C.textSec }}>RFC:</span>
                      <span>
                        {analisis.rfc_detectado || "—"}
                        {analisis.rfc_coincide === true && <span style={{ color: C.accent, marginLeft: 6 }}>✓ coincide</span>}
                      </span>
                      <span style={{ color: C.textSec }}>Presentación:</span><span>{formatoFechaHora(analisis.extraido.fecha_presentacion)}</span>
                      <span style={{ color: C.textSec }}>Número de operación:</span><span>{analisis.extraido.numero_operacion || "—"}</span>
                      <span style={{ color: C.textSec }}>Saldo a favor:</span><span>{formatoMoneda(analisis.extraido.saldo_a_favor)}</span>
                    </div>
                  </div>
                )}
              </div>

              {errorForm && (
                <div role="alert" aria-live="assertive" style={{ fontSize: 12, color: errorEsDuplicado ? C.warn : C.danger, background: errorEsDuplicado ? C.warnSoft : C.dangerSoft, borderRadius: 6, padding: "8px 10px", marginBottom: 12, marginTop: form.archivo ? 0 : 12 }}>
                  ⚠ {errorForm}
                </div>
              )}

              <div style={{ display: "flex", gap: 8 }}>
                <Btn disabled={subiendo || !puedeGuardar} style={{ flex: 1, minHeight: 44 }}>{subiendo ? "Subiendo…" : "Guardar"}</Btn>
                <Btn type="button" variant="secondary" style={{ minHeight: 44 }} disabled={subiendo} onClick={() => solicitarCierre("cancelar")}>
                  Cancelar
                </Btn>
              </div>
            </form>
          )}
        </div>
      </Card>
    </div>
  );
}
