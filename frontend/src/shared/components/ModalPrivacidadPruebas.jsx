// ─── ModalPrivacidadPruebas.jsx ─────────────────────────────────────────────
// NUEVO (08 sep 2026). No existia un Modal/Dialog generico reutilizable en el
// proyecto: hay 4 modales ad-hoc (AppShell "Cambiar contraseña",
// EditarEmisorModal, EliminarEmisorConfirm, ReemplazarCsdForm) que copian el
// mismo overlay a mano. Este componente sigue ese patron visual (overlay
// position:fixed + caja centrada sobre C.card) pero es un CONSENTIMIENTO
// OBLIGATORIO, asi que a proposito NO se puede cerrar sin aceptar: sin boton
// ×, sin cerrar por click en el backdrop, sin Escape. La unica salida es
// marcar el checkbox y dar clic en "Entendido".
//
// Contenido: conversion manual a JSX del borrador de Aviso de Privacidad +
// Acuerdo de Confidencialidad (ambiente de pruebas). El proyecto no tiene
// ningun renderer de markdown instalado (package.json: solo react/react-dom),
// asi que se transcribe a elementos JSX planos. Los textos entre [CORCHETES]
// son marcadores PENDIENTES del borrador legal, se dejan literales a
// proposito hasta que un abogado los complete.
import { useState } from "react";
import { C } from "../utils/format";

const H3 = ({ children }) => (
  <h3 style={{ fontSize: 15, fontWeight: 700, color: C.text, margin: "18px 0 6px" }}>{children}</h3>
);
const H4 = ({ children }) => (
  <h4 style={{ fontSize: 13, fontWeight: 700, color: C.text, margin: "12px 0 4px" }}>{children}</h4>
);
const P = ({ children }) => (
  <p style={{ fontSize: 13, lineHeight: 1.55, color: C.textSec, margin: "0 0 8px" }}>{children}</p>
);
const UL = ({ children }) => (
  <ul style={{ fontSize: 13, lineHeight: 1.55, color: C.textSec, margin: "0 0 8px", paddingLeft: 20 }}>{children}</ul>
);
const OL = ({ children }) => (
  <ol style={{ fontSize: 13, lineHeight: 1.55, color: C.textSec, margin: "0 0 8px", paddingLeft: 20 }}>{children}</ol>
);

export default function ModalPrivacidadPruebas({ onCerrar }) {
  const [aceptado, setAceptado] = useState(false);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-privacidad-titulo"
      style={{
        position: "fixed", inset: 0, background: "rgba(3,6,18,.62)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 200, padding: 12, boxSizing: "border-box",
      }}
    >
      <div
        style={{
          width: 620, maxWidth: "calc(100vw - 24px)", maxHeight: "calc(100dvh - 40px)",
          background: C.card, borderRadius: 12, border: `1px solid ${C.border}`,
          boxShadow: "0 22px 60px rgba(0,0,0,.4)", display: "flex", flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Encabezado de advertencia, fijo (no scrollea) */}
        <div style={{ background: C.warnSoft, borderBottom: `2px solid ${C.warn}`, padding: "16px 22px", flexShrink: 0 }}>
          <div id="modal-privacidad-titulo" style={{ fontSize: 15, fontWeight: 800, color: C.warn, letterSpacing: .2 }}>
            ⚠️ AVISO DE PRIVACIDAD Y ACUERDO DE CONFIDENCIALIDAD — AMBIENTE DE PRUEBAS
          </div>
          <div style={{ fontSize: 12, color: C.warn, marginTop: 4, fontWeight: 600 }}>
            NO USAR CON CLIENTES REALES SIN REVISIÓN LEGAL. Este documento es un punto de
            partida técnico, no un instrumento legal terminado. Antes de usarlo con un cliente
            real, o de custodiar una e.firma real de un tercero en producción, debe ser
            revisado y validado por un abogado mexicano especializado en protección de datos
            personales (LFPDPPP) y derecho fiscal.
          </div>
        </div>

        {/* Cuerpo con scroll interno */}
        <div style={{ flex: 1, overflowY: "auto", WebkitOverflowScrolling: "touch", padding: "6px 22px 14px" }}>

          <H3>PARTE 1 — Aviso de Privacidad</H3>
          <P><strong>Aviso de Privacidad — Custodia de e.firma (Firma Electrónica Avanzada del SAT)</strong></P>

          <H4>Identidad y domicilio del responsable</H4>
          <P>
            [RAZÓN SOCIAL DE ACIERTO EN TI / NOMBRE COMERCIAL], con domicilio en
            [DOMICILIO FISCAL COMPLETO], es responsable del tratamiento de tus datos
            personales conforme a lo previsto en la Ley Federal de Protección de Datos
            Personales en Posesión de los Particulares (LFPDPPP).
          </P>

          <H4>Datos personales que se tratan</H4>
          <P>Para prestarte el servicio de descarga masiva de CFDI ante el SAT, tratamos:</P>
          <UL>
            <li>Tu Registro Federal de Contribuyentes (RFC).</li>
            <li>Tu certificado de e.firma (archivo .cer, público).</li>
            <li>
              Tu llave privada de e.firma (archivo .key) y su contraseña — dato personal
              sensible, dado que su uso indebido podría comprometer tu identidad fiscal y
              patrimonial ante el SAT y otras autoridades.
            </li>
          </UL>

          <H4>Finalidades del tratamiento</H4>
          <P>Usamos estos datos ÚNICAMENTE para:</P>
          <OL>
            <li>
              Autenticarnos en tu nombre ante los servicios web de Descarga Masiva del SAT
              (Regla 2.7.2.4 de la RMF), exclusivamente cuando tú inicias una solicitud de
              descarga desde la plataforma.
            </li>
            <li>
              Solicitar, consultar el estatus, y descargar los paquetes de CFDI (emitidos
              y/o recibidos) que tú indiques, en el rango de fechas que tú elijas.
            </li>
          </OL>
          <P>
            No usamos tu e.firma para ningún otro trámite, gestión, o servicio ante el SAT
            u otra autoridad, salvo que exista una solicitud tuya explícita y adicional.
          </P>

          <H4>Consentimiento</H4>
          <P>
            Por tratarse de un dato personal sensible, requerimos tu consentimiento EXPRESO
            y por escrito (una casilla de aceptación explícita, no una casilla premarcada)
            antes de recibir o almacenar tu llave privada y contraseña.
          </P>

          <H4>Medidas de seguridad</H4>
          <UL>
            <li>
              Tu llave privada y contraseña se cifran de forma independiente entre sí, con
              una llave de cifrado exclusiva para este propósito (distinta de la que protege
              otros certificados del sistema, como tu Certificado de Sello Digital de
              facturación).
            </li>
            <li>
              El acceso está restringido a los procesos automatizados estrictamente
              necesarios para ejecutar tu solicitud de descarga — ninguna persona dentro de
              [NOMBRE DE LA EMPRESA] tiene acceso de lectura directa a tu llave privada o
              contraseña en texto plano.
            </li>
            <li>
              [PENDIENTE DE CONFIRMAR CON EL ABOGADO: detalle de controles adicionales que
              la LFPDPPP o su reglamento exijan explícitamente.]
            </li>
          </UL>

          <H4>Plazo de conservación</H4>
          <P>
            Conservamos tu e.firma únicamente mientras tu cuenta esté activa y mientras no
            solicites su eliminación. Ver Parte 2 de este documento para el procedimiento de
            destrucción.
          </P>

          <H4>Transferencias</H4>
          <P>
            No transferimos tu e.firma a ningún tercero, salvo la transmisión estrictamente
            necesaria hacia los propios servidores del SAT para ejecutar tu solicitud de
            descarga.
          </P>

          <H4>Derechos ARCO</H4>
          <P>
            Puedes en cualquier momento Acceder, Rectificar, Cancelar tu consentimiento, u
            Oponerte al tratamiento de tu e.firma, incluyendo solicitar su eliminación
            inmediata, escribiendo a [CORREO/CONTACTO DE CONTACTO PARA DERECHOS ARCO].
          </P>

          <H4>Cambios a este aviso</H4>
          <P>
            [PENDIENTE: mecanismo de notificación de cambios — ej. correo, aviso en la
            plataforma — a definir con el abogado.]
          </P>

          <H3>PARTE 2 — Procedimiento de destrucción de e.firma</H3>

          <H4>Cuándo se activa</H4>
          <P>Este procedimiento se ejecuta cuando ocurra CUALQUIERA de los siguientes casos:</P>
          <OL>
            <li>
              El cliente solicita explícitamente la eliminación de su e.firma (ejercicio del
              derecho ARCO de Cancelación).
            </li>
            <li>El cliente cancela su cuenta o suscripción en la plataforma.</li>
            <li>
              [PENDIENTE DE DEFINIR CON EL ABOGADO: ¿hay un plazo máximo de inactividad tras
              el cual se destruye automáticamente, incluso sin solicitud explícita?]
            </li>
          </OL>

          <H4>Pasos del procedimiento (borrador técnico, sujeto a validación legal)</H4>
          <OL>
            <li>
              Confirmación de identidad: verificar que la solicitud de eliminación proviene
              genuinamente del titular de la cuenta.
            </li>
            <li>
              Bloqueo inmediato de uso: marcar la e.firma como "pendiente de destrucción" en
              el sistema.
            </li>
            <li>
              Borrado criptográfico irrecuperable: eliminar de la base de datos los campos
              cifrados de la llave privada y la contraseña.
            </li>
            <li>
              Verificación de ausencia en respaldos: [PENDIENTE DE DEFINIR CON EL ABOGADO Y
              CON EL EQUIPO TÉCNICO.]
            </li>
            <li>
              Registro de la destrucción: dejar constancia interna (fecha, hora, quién
              ejecutó la eliminación, motivo).
            </li>
            <li>
              Notificación al titular: confirmar por escrito al cliente que su e.firma fue
              eliminada exitosamente.
            </li>
          </OL>

          <H4>Plazo máximo para ejecutar el procedimiento</H4>
          <P>[PENDIENTE DE DEFINIR CON EL ABOGADO.]</P>

          <H3>PARTE 3 — Acuerdo de Confidencialidad (Ambiente de Pruebas)</H3>
          <P><strong>Acuerdo de Confidencialidad — Ambiente de Pruebas</strong></P>
          <P>Al continuar, reconoces y aceptas que:</P>
          <OL>
            <li>
              Este es un ambiente de pruebas (pre-producción), no el entorno productivo
              final de [NOMBRE DE LA EMPRESA]. Las medidas de seguridad, validaciones
              legales, y controles descritos en el Aviso de Privacidad de la Parte 1 pueden
              estar incompletos o en proceso de revisión.
            </li>
            <li>
              Confidencialidad de lo que descubras: te comprometes a NO divulgar públicamente
              ningún hallazgo de seguridad, vulnerabilidad, error, o dato real de otra
              persona/negocio al que tengas acceso incidental durante tus pruebas. Debes
              reportarlo directamente a [CONTACTO DEL EQUIPO], no exponerlo públicamente.
            </li>
            <li>
              Uso de datos reales bajo tu propio riesgo: si decides aportar información
              fiscal real (como tu propia e.firma) para probar funcionalidades, lo haces de
              forma voluntaria y consciente de que es un ambiente de pruebas.
            </li>
            <li>
              Confidencialidad recíproca: [NOMBRE DE LA EMPRESA] se compromete, de forma
              recíproca, a mantener confidencial cualquier dato que subas durante las
              pruebas.
            </li>
            <li>
              Vigencia: este acuerdo aplica mientras participes en el ambiente de pruebas, y
              las obligaciones de confidencialidad sobrevivirán a la terminación de tu
              participación por [PENDIENTE DE DEFINIR: plazo].
            </li>
          </OL>
        </div>

        {/* Pie fijo: checkbox de consentimiento + boton */}
        <div style={{ borderTop: `1px solid ${C.border}`, padding: "14px 22px", flexShrink: 0, background: C.card }}>
          <label style={{ display: "flex", alignItems: "flex-start", gap: 9, cursor: "pointer", marginBottom: 12 }}>
            <input
              type="checkbox"
              checked={aceptado}
              onChange={(e) => setAceptado(e.target.checked)}
              style={{ width: 16, height: 16, marginTop: 1, flexShrink: 0, cursor: "pointer", accentColor: C.accent }}
            />
            <span style={{ fontSize: 13, color: C.text, lineHeight: 1.45 }}>
              He leído y acepto el Acuerdo de Confidencialidad del Ambiente de Pruebas.
            </span>
          </label>
          {!aceptado && (
            <div style={{ fontSize: 11, color: C.textMuted, marginBottom: 10 }}>
              Marca la casilla para continuar.
            </div>
          )}
          <button
            type="button"
            onClick={onCerrar}
            disabled={!aceptado}
            style={{
              width: "100%", padding: "12px 16px", borderRadius: 8, border: "none",
              background: C.accent, color: "#fff", fontWeight: 700, fontSize: 14,
              cursor: aceptado ? "pointer" : "not-allowed", opacity: aceptado ? 1 : 0.5,
            }}
          >
            Entendido
          </button>
        </div>
      </div>
    </div>
  );
}
