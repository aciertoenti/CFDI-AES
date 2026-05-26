// src/hooks/useIA.js
// Hook React para consumir el microservicio IA (puerto 8006)
// Cubre: extracción de PDFs, chat fiscal streaming y anomalías

import { useState, useCallback, useRef } from "react";

const IA_BASE = import.meta.env.VITE_IA_URL || "http://localhost:8006";

// ─── 1. Extractor de documentos ───────────────────────────────────────────────
export function useDocumentExtractor() {
  const [loading, setLoading]   = useState(false);
  const [result,  setResult]    = useState(null);
  const [error,   setError]     = useState(null);
  const [progress, setProgress] = useState([]);

  const extraer = useCallback(async (file) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setProgress([]);

    const steps = [
      "Leyendo documento…",
      "IA identificando campos fiscales…",
      "Validando RFC en SAT…",
      "Construyendo borrador CFDI…",
    ];

    // Simulamos progreso visual mientras la API trabaja
    steps.forEach((msg, i) => {
      setTimeout(() => setProgress((p) => [...p, msg]), i * 900);
    });

    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`${IA_BASE}/ia/extraer-documento`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Error en extracción");
      }

      const data = await res.json();
      setResult(data);
      return data;
    } catch (e) {
      setError(e.message);
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  return { extraer, loading, result, error, progress };
}


// ─── 2. Chat fiscal con streaming ─────────────────────────────────────────────
export function useFiscalChat() {
  const [messages,  setMessages]  = useState([]);
  const [streaming, setStreaming] = useState(false);
  const [error,     setError]     = useState(null);
  const abortRef = useRef(null);

  const sendMessage = useCallback(async (userText, contextoCuenta = {}) => {
    const userMsg = { role: "user", content: userText };
    const newHistory = [...messages, userMsg];
    setMessages(newHistory);
    setStreaming(true);
    setError(null);

    // Placeholder del asistente que iremos rellenando con tokens
    const assistantMsg = { role: "assistant", content: "" };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      abortRef.current = new AbortController();

      const res = await fetch(`${IA_BASE}/ia/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: abortRef.current.signal,
        body: JSON.stringify({
          messages: newHistory,
          contexto_cuenta: contextoCuenta,
        }),
      });

      if (!res.ok) throw new Error("Error en el chat");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop(); // Línea incompleta queda en buffer

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (raw === "[DONE]") break;

          try {
            const { token } = JSON.parse(raw);
            setMessages((prev) => {
              const updated = [...prev];
              updated[updated.length - 1] = {
                role: "assistant",
                content: updated[updated.length - 1].content + token,
              };
              return updated;
            });
          } catch {}
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        setError(e.message);
        setMessages((prev) => prev.slice(0, -1)); // Quitar placeholder vacío
      }
    } finally {
      setStreaming(false);
    }
  }, [messages]);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, []);

  const reset = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  return { messages, sendMessage, streaming, abort, reset, error };
}


// ─── 3. Detección de anomalías ────────────────────────────────────────────────
export function useAnomalias() {
  const [anomalias, setAnomalias] = useState([]);
  const [loading,   setLoading]   = useState(false);
  const [lastRun,   setLastRun]   = useState(null);

  const detectar = useCallback(async ({ facturas, pagos_bancarios = [], clientes = [] }) => {
    setLoading(true);
    try {
      const res = await fetch(`${IA_BASE}/ia/anomalias`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ facturas, pagos_bancarios, clientes }),
      });
      if (!res.ok) throw new Error("Error detectando anomalías");
      const data = await res.json();
      setAnomalias(data);
      setLastRun(new Date());
      return data;
    } catch (e) {
      console.error("Anomalías:", e.message);
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  return { anomalias, detectar, loading, lastRun };
}


// ─── 4. Conciliación bancaria ─────────────────────────────────────────────────
export function useConciliacion() {
  const [resultado, setResultado] = useState(null);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState(null);

  const conciliar = useCallback(async (facturas, depositos, tolerancia = 5.0) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${IA_BASE}/ia/conciliar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ facturas, depositos, tolerancia_porcentaje: tolerancia }),
      });
      if (!res.ok) throw new Error("Error en conciliación");
      const data = await res.json();
      setResultado(data);
      return data;
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  return { resultado, conciliar, loading, error };
}


// ─── 5. Resumen ejecutivo ─────────────────────────────────────────────────────
export function useResumenEjecutivo() {
  const [resumen,  setResumen]  = useState(null);
  const [loading,  setLoading]  = useState(false);

  const generar = useCallback(async (periodoInicio, periodoFin, datosFacturacion) => {
    setLoading(true);
    try {
      const res = await fetch(`${IA_BASE}/ia/resumen-ejecutivo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          periodo_inicio: periodoInicio,
          periodo_fin: periodoFin,
          datos_facturacion: datosFacturacion,
          incluir_comparativo: true,
        }),
      });
      if (!res.ok) throw new Error("Error generando resumen");
      const data = await res.json();
      setResumen(data);
      return data;
    } finally {
      setLoading(false);
    }
  }, []);

  return { resumen, generar, loading };
}
