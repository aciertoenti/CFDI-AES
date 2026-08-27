import { useState } from "react";
import { useToast } from "../../shared/layout/ToastProvider";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Btn, Card, SectionTitle, SectionSub } from "../../shared/components/atoms";
import { C, detalleError } from "../../shared/utils/format";

export default function EliminarEmisorConfirm({ emisor, onCerrar, recargar }) {
  const toast = useToast();
  const [confirmacionRfc, setConfirmacionRfc] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(null);

  // Mismo criterio case-insensitive que ReemplazarCsdForm.
  const coincide = confirmacionRfc.trim().toUpperCase() === emisor.rfc.toUpperCase();

  const submit = async e => {
    e.preventDefault();
    setError(null);
    // Defensa en profundidad: no confiar solo en el disabled del boton.
    if (!coincide) {
      setError("El texto de confirmación no coincide con el RFC del emisor.");
      return;
    }
    setEnviando(true);
    try {
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.rfc}`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      // 409: el emisor tiene facturas timbradas - se muestra el mensaje real
      // del backend (dice explícitamente "Usa 'Inactivar' en su lugar").
      // 503: no se pudo verificar el conteo de facturas - el backend falla
      // cerrado a proposito, no se ofrece forzar.
      if (res.status === 409 || res.status === 503) {
        setError(data.detail || "No se pudo eliminar el emisor.");
        return;
      }
      if (!res.ok) throw new Error(detalleError(data, res));
      toast(`Emisor ${emisor.rfc} eliminado`, "success");
      recargar();
      onCerrar();
    } catch (e) {
      setError(e.message);
      toast(`Error al eliminar emisor: ${e.message}`, "error");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(3,6,18,.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 120 }} onClick={onCerrar}>
      <Card style={{ width: 400, maxWidth: "calc(100vw - 24px)", maxHeight: "calc(100vh - 40px)", overflowY: "auto", position: "relative" }} onClick={e => e.stopPropagation()}>
        <SectionTitle>Eliminar emisor</SectionTitle>
        <SectionSub>Esta acción es irreversible. Si el emisor tiene facturas timbradas no se podrá eliminar — usa "Inactivar" en su lugar.</SectionSub>

        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px", marginBottom: 16, fontSize: 13 }}>
          <div style={{ color: C.text, fontWeight: 600, marginBottom: 4 }}>{emisor.razon_social}</div>
          <div style={{ color: C.textMuted, fontFamily: "monospace", marginBottom: 6 }}>{emisor.rfc}</div>
          <div style={{ color: C.textSec }}>Régimen fiscal: <strong style={{ color: C.text }}>{emisor.regimen_fiscal}</strong></div>
          <div style={{ color: C.textSec }}>CP expedición: <strong style={{ color: C.text }}>{emisor.codigo_postal}</strong></div>
        </div>

        <form onSubmit={submit} autoComplete="off">
          <div style={{ marginBottom: 8 }}>
            <label style={{ fontSize: 12, color: C.textSec, display: "block", marginBottom: 3 }}>
              Escribe el RFC "{emisor.rfc}" para confirmar la eliminación.
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

          {error && <div style={{ fontSize: 12, color: C.danger, marginBottom: 14, padding: "8px 10px", background: C.dangerSoft, borderRadius: 6 }}>⚠ {error}</div>}

          <div style={{ display: "flex", gap: 8 }}>
            <Btn disabled={enviando || !coincide} style={{ flex: 1, background: C.danger, color: "#fff" }}>{enviando ? "Eliminando…" : "Eliminar emisor"}</Btn>
            <Btn type="button" variant="secondary" onClick={onCerrar} disabled={enviando}>Cancelar</Btn>
          </div>
        </form>
      </Card>
    </div>
  );
}
