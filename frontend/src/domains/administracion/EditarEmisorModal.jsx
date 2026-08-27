import { useState } from "react";
import { useToast } from "../../shared/layout/ToastProvider";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Btn, Card } from "../../shared/components/atoms";
import { C, detalleError } from "../../shared/utils/format";

export default function EditarEmisorModal({ emisor, onCerrar, recargar }) {
  const toast = useToast();
  const [form, setForm] = useState({
    razon_social: emisor.razon_social,
    regimen_fiscal: emisor.regimen_fiscal,
    codigo_postal: emisor.codigo_postal,
  });
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(null);

  const submit = async e => {
    e.preventDefault();
    setError(null);
    setEnviando(true);
    try {
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.rfc}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detalleError(data, res));
      toast(`Emisor ${emisor.rfc} actualizado correctamente`, "success");
      recargar();
      onCerrar();
    } catch (e) {
      setError(e.message);
      toast(`Error al actualizar emisor: ${e.message}`, "error");
    } finally {
      setEnviando(false);
    }
  };

  const inp = (label, key, opts = {}) => (
    <div style={{ marginBottom: 12 }}>
      <label style={{ fontSize: 12, color: C.textSec, display: "block", marginBottom: 3 }}>{label}</label>
      <input
        type="text"
        value={form[key]}
        maxLength={opts.maxLength}
        onChange={e => setForm({ ...form, [key]: e.target.value })}
        style={{ width: "100%", border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 11px", fontSize: 13, color: C.text, background: "#fff", boxSizing: "border-box" }}
      />
    </div>
  );

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(3,6,18,.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 120 }} onClick={onCerrar}>
      <Card style={{ width: 380, maxWidth: "calc(100vw - 24px)", position: "relative" }} onClick={e => e.stopPropagation()}>
        <div style={{ fontSize: 16, fontWeight: 700, color: C.text, marginBottom: 4 }}>Editar emisor</div>
        <div style={{ fontSize: 12, color: C.textMuted, fontFamily: "monospace", marginBottom: 16 }}>{emisor.rfc}</div>
        <form onSubmit={submit}>
          {inp("Razón social", "razon_social")}
          {inp("Régimen fiscal (código SAT)", "regimen_fiscal", { maxLength: 3 })}
          {inp("Código postal de expedición", "codigo_postal", { maxLength: 5 })}
          {error && <div style={{ fontSize: 12, color: C.danger, marginBottom: 14, padding: "8px 10px", background: C.dangerSoft, borderRadius: 6 }}>⚠ {error}</div>}
          <div style={{ display: "flex", gap: 8 }}>
            <Btn disabled={enviando} style={{ flex: 1 }}>{enviando ? "Guardando…" : "Guardar cambios"}</Btn>
            <Btn type="button" variant="secondary" onClick={onCerrar} disabled={enviando}>Cancelar</Btn>
          </div>
        </form>
      </Card>
    </div>
  );
}
