import { useRef, useState } from "react";
import { useToast } from "../../shared/layout/ToastProvider";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Btn, Card, SectionTitle, SectionSub } from "../../shared/components/atoms";
import { C, detalleError } from "../../shared/utils/format";

export default function ReemplazarCsdForm({ emisor, onCerrar, recargar }) {
  const toast = useToast();
  const [csdPassword, setCsdPassword] = useState("");
  const [confirmacionRfc, setConfirmacionRfc] = useState("");
  const [cerFile, setCerFile] = useState(null), [keyFile, setKeyFile] = useState(null), [enviando, setEnviando] = useState(false), [error, setError] = useState(null);
  const [cacheInvalidadoFalse, setCacheInvalidadoFalse] = useState(false);
  const cerInputRef = useRef(), keyInputRef = useRef();

  const fileToBase64 = file => new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1] || ""); reader.onerror = () => reject(new Error("No se pudo leer el archivo")); reader.readAsDataURL(file); });

  const coincide = confirmacionRfc.trim().toUpperCase() === emisor.rfc.toUpperCase();

  const submit = async e => {
    e.preventDefault();
    setError(null);
    // Defensa en profundidad: no confiar solo en el disabled del boton.
    if (confirmacionRfc.trim().toUpperCase() !== emisor.rfc.toUpperCase()) {
      setError("El texto de confirmación no coincide con el RFC del emisor.");
      return;
    }
    if (!csdPassword) {
      setError("La contraseña del CSD es obligatoria.");
      return;
    }
    if (!cerFile || !keyFile) {
      setError("Sube los dos archivos del CSD (.cer y .key).");
      return;
    }
    setEnviando(true);
    try {
      const [csd_cert_base64, csd_key_base64] = await Promise.all([fileToBase64(cerFile), fileToBase64(keyFile)]);
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.rfc}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          razon_social: emisor.razon_social,
          rfc: emisor.rfc,
          regimen_fiscal: emisor.regimen_fiscal,
          codigo_postal: emisor.codigo_postal,
          csd_cert_base64,
          csd_key_base64,
          csd_password: csdPassword,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detalleError(data, res));
      if (data.cache_invalidado === false) {
        setCacheInvalidadoFalse(true);
        toast(`Certificado de ${emisor.rfc} reemplazado, pero facturación podría no haber invalidado su caché`, "error");
      } else {
        toast(`Certificado de ${emisor.rfc} reemplazado correctamente`, "success");
      }
      setConfirmacionRfc("");
      setCsdPassword("");
      setCerFile(null); setKeyFile(null);
      if (cerInputRef.current) cerInputRef.current.value = "";
      if (keyInputRef.current) keyInputRef.current.value = "";
      recargar();
      onCerrar();
    } catch (e) {
      setError(e.message);
      toast(`Error al reemplazar certificado: ${e.message}`, "error");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(3,6,18,.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 120 }} onClick={onCerrar}>
      <Card style={{ width: 420, maxWidth: "calc(100vw - 24px)", maxHeight: "calc(100vh - 40px)", overflowY: "auto", position: "relative" }} onClick={e => e.stopPropagation()}>
        <SectionTitle>Reemplazar certificado</SectionTitle>
        <SectionSub>Sube el nuevo CSD para este emisor. Los datos fiscales no se modifican aquí.</SectionSub>

        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px", marginBottom: 16, fontSize: 13 }}>
          <div style={{ color: C.text, fontWeight: 600, marginBottom: 4 }}>{emisor.razon_social}</div>
          <div style={{ color: C.textMuted, fontFamily: "monospace", marginBottom: 6 }}>{emisor.rfc}</div>
          <div style={{ color: C.textSec }}>Régimen fiscal: <strong style={{ color: C.text }}>{emisor.regimen_fiscal}</strong></div>
          <div style={{ color: C.textSec }}>CP expedición: <strong style={{ color: C.text }}>{emisor.codigo_postal}</strong></div>
        </div>

        <form onSubmit={submit} autoComplete="off">
          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, color: C.textSec, display: "block", marginBottom: 3 }}>Certificado (.cer)</label>
            <input ref={cerInputRef} type="file" accept=".cer" onChange={e => setCerFile(e.target.files[0] || null)} style={{ width: "100%", fontSize: 12, color: C.text }} />
          </div>
          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, color: C.textSec, display: "block", marginBottom: 3 }}>Llave privada (.key)</label>
            <input ref={keyInputRef} type="file" accept=".key" onChange={e => setKeyFile(e.target.files[0] || null)} style={{ width: "100%", fontSize: 12, color: C.text }} />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 12, color: C.textSec, display: "block", marginBottom: 3 }}>Contraseña del CSD</label>
            <input type="password" value={csdPassword} autoComplete="new-password" onChange={e => setCsdPassword(e.target.value)} style={{ width: "100%", border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 11px", fontSize: 13, color: C.text, background: "#fff", boxSizing: "border-box" }} />
          </div>

          <div style={{ marginBottom: 8 }}>
            <label style={{ fontSize: 12, color: C.textSec, display: "block", marginBottom: 3 }}>
              Escribe el RFC "{emisor.rfc}" para confirmar el reemplazo del certificado.
            </label>
            <input
              type="text"
              value={confirmacionRfc}
              onChange={e => setConfirmacionRfc(e.target.value)}
              style={{ width: "100%", border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 11px", fontSize: 13, color: C.text, background: "#fff", boxSizing: "border-box" }}
            />
            {confirmacionRfc.length > 0 && !coincide && (
              <div style={{ fontSize: 11, color: C.textMuted, marginTop: 4 }}>El texto debe coincidir con el RFC del emisor</div>
            )}
          </div>

          {cacheInvalidadoFalse && (
            <div style={{ fontSize: 12, color: "#7a5b00", background: "#fff6da", border: "1px solid #f0d878", padding: "8px 10px", borderRadius: 6, marginBottom: 12 }}>
              El certificado se reemplazó, pero no se pudo confirmar que facturación invalidó su caché anterior - podría seguir usando el certificado viejo temporalmente.
            </div>
          )}
          {error && <div style={{ fontSize: 12, color: C.danger, marginBottom: 14, padding: "8px 10px", background: C.dangerSoft, borderRadius: 6 }}>⚠ {error}</div>}

          <div style={{ display: "flex", gap: 8 }}>
            <Btn disabled={enviando || !coincide} style={{ flex: 1 }}>{enviando ? "Reemplazando…" : "Reemplazar certificado"}</Btn>
            <Btn type="button" variant="secondary" onClick={onCerrar} disabled={enviando}>Cancelar</Btn>
          </div>
        </form>
      </Card>
    </div>
  );
}
