import { useState, useCallback, useEffect, useRef } from "react";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";

// ═══════════════════════════════════════════════════════════════════════════════
// HOOKS IA
// ═══════════════════════════════════════════════════════════════════════════════
// Los 4 endpoints de IA ya pasan por el Gateway via API_BASE (13 ago 2026,
// rewiring de IA) - antes usaban IA_BASE directo al microservicio, sin JWT
// (ver #48/#65). useFiscalChat usa una ruta dedicada del Gateway
// (/ia/chat/stream) en vez del proxy generico, por el streaming SSE.

export function useDocumentExtractor() {
  const [loading, setLoading] = useState(false);
  const [result,  setResult]  = useState(null);
  const [error,   setError]   = useState(null);
  const [steps,   setSteps]   = useState([]);
  const extraer = useCallback(async (file) => {
    setLoading(true); setError(null); setResult(null); setSteps([]);
    const labels = ["Leyendo documento…","IA identificando campos fiscales…","Validando RFC en SAT…","Construyendo borrador CFDI…"];
    labels.forEach((l, i) => setTimeout(() => setSteps(p => [...p, l]), i * 900));
    try {
      const fd = new FormData(); fd.append("file", file);
      const res = await fetchAuth(`${API_BASE}/ia/extraer-documento`, { method:"POST", body:fd });
      if (!res.ok) throw new Error((await res.json()).detail || "Error");
      const data = await res.json(); setResult(data); return data;
    } catch(e) { setError(e.message); } finally { setLoading(false); }
  }, []);
  return { extraer, loading, result, error, steps };
}

export function useFiscalChat() {
  const [messages,  setMessages]  = useState([]);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef(null);
  const send = useCallback(async (text, ctx = {}, modo = "cuenta") => {
    const history = [...messages, { role:"user", content:text }];
    setMessages([...history, { role:"assistant", content:"" }]);
    setStreaming(true);
    abortRef.current = new AbortController();
    try {
      // Ruta dedicada del Gateway (13 ago 2026, rewiring de IA) - no pasa por
      // el proxy() generico (StreamingResponse no funciona con resp.json()).
      // fetchAuth() sigue sirviendo tal cual: solo agrega el header
      // Authorization, la respuesta que devuelve es el mismo objeto Response
      // que fetch() normal, asi que res.body.getReader() de abajo no cambia.
      // modo "general" (20 ago 2026, tarjeta 2mSpU) - contexto_cuenta ni
      // siquiera se incluye en el body, no solo se manda vacio, para que
      // quede honesto en Network tab que no se envio nada de la cuenta.
      const res = await fetchAuth(`${API_BASE}/ia/chat/stream`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        signal:abortRef.current.signal,
        body: JSON.stringify({
          messages:history,
          modo,
          ...(modo === "cuenta" ? { contexto_cuenta: ctx } : {}),
        }),
      });
      const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream:true });
        const lines = buf.split("\n"); buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim(); if (raw === "[DONE]") break;
          try { const { token } = JSON.parse(raw); setMessages(p => { const u=[...p]; u[u.length-1]={role:"assistant",content:u[u.length-1].content+token}; return u; }); } catch {}
        }
      }
    } catch(e) { if (e.name !== "AbortError") setMessages(p => p.slice(0,-1)); }
    finally { setStreaming(false); }
  }, [messages]);
  return { messages, send, streaming, reset:()=>setMessages([]), abort:()=>{ abortRef.current?.abort(); setStreaming(false); } };
}

export function useAnomalias() {
  const [anomalias, setAnomalias] = useState([]);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState(null);
  const detectar = useCallback(async (facturas, pagos=[]) => {
    setLoading(true); setError(null);
    try {
      const res = await fetchAuth(`${API_BASE}/ia/anomalias`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ facturas, pagos_bancarios:pagos }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP ${res.status}`);
      }
      const data = await res.json(); setAnomalias(data); return data;
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  return { anomalias, detectar, loading, error };
}
