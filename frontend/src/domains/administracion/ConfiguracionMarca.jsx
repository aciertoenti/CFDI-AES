import { useEffect, useRef, useState } from "react";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Card, Btn } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";

// White-label del portal de autofacturación pública (zg2mOhE) -
// PortalAutofacturacion.jsx lee logo_url/color_primario del negocio via
// GET /facturas/tickets/{qr_token} (branding cruzado desde administracion).
// Este componente es donde el negocio los configura.
//
// Flujo de guardado en 2 pasos, igual que el backend (ver
// POST /admin/config/logo + PUT /admin/config): si el usuario eligió un
// archivo nuevo, primero se sube (con preview local inmediato via
// URL.createObjectURL, antes de tocar el backend) y solo al hacer clic en
// "Guardar" se sube de verdad y se persiste junto con el color.

const HEX_VALIDO = /^#[0-9A-Fa-f]{6}$/;
const COLOR_DEFAULT = "#00C896"; // mismo C.accent que usa la marca actual

export default function ConfiguracionMarca() {
  const [logoUrlGuardado, setLogoUrlGuardado] = useState(null);
  const [colorPrimario, setColorPrimario] = useState(COLOR_DEFAULT);
  const [archivoNuevo, setArchivoNuevo] = useState(null);
  const [previewLocal, setPreviewLocal] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [mensaje, setMensaje] = useState(null); // { tipo: "ok"|"error", texto }
  const inputArchivoRef = useRef(null);

  useEffect(() => {
    let cancelado = false;
    (async () => {
      try {
        const res = await fetchAuth(`${API_BASE}/admin/config`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelado) {
          setLogoUrlGuardado(data.logo_url || null);
          setColorPrimario(data.color_primario || COLOR_DEFAULT);
        }
      } catch {
        // Silencioso: si falla, simplemente arranca en blanco/default -
        // el usuario puede configurar de cero sin que la pantalla se rompa.
      } finally {
        if (!cancelado) setCargando(false);
      }
    })();
    return () => { cancelado = true; };
  }, []);

  const elegirArchivo = e => {
    const file = e.target.files?.[0];
    if (!file) return;
    setArchivoNuevo(file);
    setPreviewLocal(URL.createObjectURL(file));
    setMensaje(null);
  };

  const guardar = async () => {
    setMensaje(null);
    if (!HEX_VALIDO.test(colorPrimario)) {
      setMensaje({ tipo: "error", texto: "El color debe ser un hex válido, ej. #00C896." });
      return;
    }
    setGuardando(true);
    try {
      let logoUrlFinal = logoUrlGuardado;
      if (archivoNuevo) {
        const formData = new FormData();
        formData.append("archivo", archivoNuevo);
        const resLogo = await fetchAuth(`${API_BASE}/admin/config/logo`, { method: "POST", body: formData });
        const dataLogo = await resLogo.json().catch(() => ({}));
        if (!resLogo.ok) throw new Error(dataLogo.detail || `HTTP ${resLogo.status}`);
        logoUrlFinal = dataLogo.logo_url;
      }

      const resConfig = await fetchAuth(`${API_BASE}/admin/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ logo_url: logoUrlFinal, color_primario: colorPrimario }),
      });
      const dataConfig = await resConfig.json().catch(() => ({}));
      if (!resConfig.ok) throw new Error(dataConfig.detail || `HTTP ${resConfig.status}`);

      setLogoUrlGuardado(dataConfig.logo_url || null);
      setColorPrimario(dataConfig.color_primario || COLOR_DEFAULT);
      setArchivoNuevo(null);
      setPreviewLocal(null);
      if (inputArchivoRef.current) inputArchivoRef.current.value = "";
      setMensaje({ tipo: "ok", texto: "Marca guardada. Los nuevos tickets ya la mostrarán en el portal público." });
    } catch (e) {
      setMensaje({ tipo: "error", texto: e.message });
    } finally {
      setGuardando(false);
    }
  };

  const logoAMostrar = previewLocal || logoUrlGuardado;

  return (
    <Card>
      <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 4 }}>Marca del portal público</div>
      <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 14 }}>
        Logo y color que verán tus clientes al autofacturarse desde el portal público (escaneando el QR del ticket). Si no configuras nada, se usa la marca de CFDI-AES.
      </div>

      {cargando ? (
        <div style={{ fontSize: 13, color: C.textMuted, padding: "8px 0" }}>Cargando…</div>
      ) : (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 14 }}>
            <div style={{
              width: 64, height: 64, borderRadius: 8, border: `1px solid ${C.border}`,
              display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", flexShrink: 0, background: "#fff",
            }}>
              {logoAMostrar
                ? <img src={logoAMostrar} alt="Logo del negocio" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />
                : <span style={{ fontSize: 10, color: C.textMuted, textAlign: "center", padding: 4 }}>Sin logo</span>}
            </div>
            <div>
              <input
                ref={inputArchivoRef}
                type="file"
                accept="image/png,image/jpeg,image/svg+xml"
                onChange={elegirArchivo}
                style={{ fontSize: 12 }}
              />
              <div style={{ fontSize: 11, color: C.textMuted, marginTop: 4 }}>PNG, JPG o SVG · máx. 2MB</div>
            </div>
          </div>

          <label style={{ fontSize: 12, color: C.textSec, display: "block", marginBottom: 4, fontWeight: 600 }}>Color primario</label>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
            <input
              type="color"
              value={HEX_VALIDO.test(colorPrimario) ? colorPrimario : COLOR_DEFAULT}
              onChange={e => setColorPrimario(e.target.value)}
              style={{ width: 44, height: 32, padding: 0, border: `1px solid ${C.border}`, borderRadius: 6, cursor: "pointer" }}
            />
            <input
              type="text"
              value={colorPrimario}
              onChange={e => setColorPrimario(e.target.value)}
              placeholder="#00C896"
              style={{ width: 110, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px", fontSize: 13, fontFamily: "monospace" }}
            />
          </div>

          {mensaje && (
            <div style={{ fontSize: 12, color: mensaje.tipo === "ok" ? "#0A6B4A" : C.danger, marginBottom: 10 }}>
              {mensaje.texto}
            </div>
          )}

          <Btn type="button" onClick={guardar} disabled={guardando} style={{ fontSize: 12, padding: "8px 16px" }}>
            {guardando ? "Guardando…" : "Guardar marca"}
          </Btn>
        </>
      )}
    </Card>
  );
}
