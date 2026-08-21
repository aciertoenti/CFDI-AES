import { createContext, useCallback, useContext, useState } from "react";

const ToastCtx = createContext(null);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const add = useCallback((msg, type = "info", duration = 3500) => {
    const id = Date.now() + Math.random();
    setToasts(p => [...p, { id, msg, type }]);
    setTimeout(() => setToasts(p => p.filter(t => t.id !== id)), duration);
  }, []);
  const remove = id => setToasts(p => p.filter(t => t.id !== id));
  const typeStyle = {
    info:    { bg: "#0A2540", color: "#E8F4FF",  icon: "ℹ" },
    success: { bg: "#0A4A35", color: "#E6FAF5",  icon: "✓" },
    warning: { bg: "#4A2800", color: "#FFF0D6",  icon: "⚠" },
    error:   { bg: "#4A0A0A", color: "#FFE8E8",  icon: "✕" },
    api:     { bg: "#1A1A2E", color: "#C8D8FF",  icon: "⚡" },
  };
  return (
    <ToastCtx.Provider value={add}>
      {children}
      <div style={{ position:"fixed", bottom:80, right:16, zIndex:999, display:"flex", flexDirection:"column", gap:8, maxWidth:340, pointerEvents:"none" }}>
        {toasts.map(t => {
          const s = typeStyle[t.type] || typeStyle.info;
          return (
            <div key={t.id} onClick={() => remove(t.id)}
              style={{ background:s.bg, color:s.color, borderRadius:10, padding:"10px 14px", fontSize:13, lineHeight:1.45,
                display:"flex", alignItems:"flex-start", gap:10, pointerEvents:"all", cursor:"pointer",
                boxShadow:"0 4px 20px rgba(0,0,0,.35)", animation:"toastIn .2s ease",
                fontFamily:"'Inter',system-ui,sans-serif", wordBreak:"break-word" }}>
              <span style={{ flexShrink:0, fontSize:15, marginTop:1 }}>{s.icon}</span>
              <span>{t.msg}</span>
            </div>
          );
        })}
      </div>
      <style>{`@keyframes toastIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}`}</style>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
