// ─── App.jsx ── CFDI-AES · Responsive + Toast + Table fix ─────────────────────
import { useState, useEffect, useCallback, useRef, createContext, useContext } from "react";
import logoAcierto from "./assets/logo-acierto.png";

// ═══════════════════════════════════════════════════════════════════════════════
// BREAKPOINT
// ═══════════════════════════════════════════════════════════════════════════════
function useBreakpoint() {
  const [w, setW] = useState(typeof window !== "undefined" ? window.innerWidth : 1200);
  useEffect(() => {
    const h = () => setW(window.innerWidth);
    window.addEventListener("resize", h);
    return () => window.removeEventListener("resize", h);
  }, []);
  return { w, isMobile: w < 768, isTablet: w >= 768 && w < 1024, isDesktop: w >= 1024 };
}

// ═══════════════════════════════════════════════════════════════════════════════
// TOAST SYSTEM — reemplaza todos los alert()
// ═══════════════════════════════════════════════════════════════════════════════
const ToastCtx = createContext(null);

function ToastProvider({ children }) {
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
      {/* Toast container */}
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

const useToast = () => useContext(ToastCtx);

// ═══════════════════════════════════════════════════════════════════════════════
// HOOKS IA
// ═══════════════════════════════════════════════════════════════════════════════
// Los 4 endpoints de IA ya pasan por el Gateway via API_BASE (13 ago 2026,
// rewiring de IA) - antes usaban IA_BASE directo al microservicio, sin JWT
// (ver #48/#65). useFiscalChat usa una ruta dedicada del Gateway
// (/ia/chat/stream) en vez del proxy generico, por el streaming SSE.
const API_BASE = "http://localhost:8000";
// FACTURACION_BASE/ADMINISTRACION_BASE/AUTH_BASE ya no se usan para fetch
// real (ver #48) - se dejan solo porque siguen apareciendo en textos de
// error (ej. "No se pudo conectar con administracion (${ADMINISTRACION_BASE})").
const FACTURACION_BASE = "http://localhost:8001";
const ADMINISTRACION_BASE = "http://localhost:8002";
const AUTH_BASE = "http://localhost:8005";

// ─── Autenticacion (#48) ────────────────────────────────────────────────────
const TOKEN_KEY = "cfdi_aes_token";
const getToken = () => sessionStorage.getItem(TOKEN_KEY);
const setStoredToken = t => t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY);

async function fetchAuth(url, options = {}) {
  const token = getToken();
  const headers = { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401 || res.status === 403) {
    setStoredToken(null);
    window.dispatchEvent(new Event("cfdi-auth-expired"));
  }
  return res;
}

function useAuth() {
  const [token, setToken] = useState(getToken);
  useEffect(() => {
    const onExpired = () => setToken(null);
    window.addEventListener("cfdi-auth-expired", onExpired);
    return () => window.removeEventListener("cfdi-auth-expired", onExpired);
  }, []);
  const login = useCallback(async (identificador, password) => {
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        // identificador acepta RFC personal O usuario indistintamente (ver
        // auth_usuarios: LoginRequest.identificador) - el backend decide
        // cual es segun la longitud/formato, el frontend no distingue.
        body: JSON.stringify({ identificador, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: detalleError(data, res) };
      setStoredToken(data.access_token);
      setToken(data.access_token);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, []);
  const registro = useCallback(async (nombreNegocio, email, rfcPersonal, password, nombre, usuario) => {
    try {
      const res = await fetch(`${API_BASE}/auth/registro`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nombre_negocio: nombreNegocio, email, rfc_personal: rfcPersonal, password, nombre, usuario }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: detalleError(data, res) };
      // POST /auth/registro (#15) crea el Negocio + primer usuario admin pero
      // no regresa token - se reusa login() con las mismas credenciales para
      // entrar directo tras crear la cuenta.
      return login(rfcPersonal, password);
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, [login]);
  const logout = useCallback(() => { setStoredToken(null); setToken(null); }, []);
  // Recuperacion de contrasena (14 ago 2026) - ambas publicas, mismo patron
  // que login/registro arriba (sin fetchAuth, no hay token todavia). La
  // respuesta de solicitarReset es deliberadamente identica exista o no la
  // cuenta (ver backend) - este hook solo la pasa tal cual, no interpreta nada.
  const solicitarReset = useCallback(async (email) => {
    try {
      const res = await fetch(`${API_BASE}/auth/password-reset/request`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: detalleError(data, res) };
      return { ok: true, mensaje: data.mensaje };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, []);
  const confirmarReset = useCallback(async (token, nuevaPassword) => {
    try {
      const res = await fetch(`${API_BASE}/auth/password-reset/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, nueva_password: nuevaPassword }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: detalleError(data, res) };
      return { ok: true, mensaje: data.mensaje };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, []);
  return { token, isAuthenticated: !!token, login, registro, logout, solicitarReset, confirmarReset };
}

function Login({ onLogin, onIrARegistro, onIrAOlvide }) {
  const [identificador, setIdentificador] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const submit = async e => {
    e.preventDefault();
    setLoading(true); setError(null);
    const r = await onLogin(identificador, password);
    setLoading(false);
    if (!r.ok) setError(r.error);
  };

  return (
    <div style={{minHeight:"100dvh",display:"flex",alignItems:"center",justifyContent:"center",background:C.surface,padding:20,boxSizing:"border-box"}}>
      <form onSubmit={submit} style={{background:C.card,padding:"28px 22px",borderRadius:12,width:340,maxWidth:"100%",boxShadow:"0 4px 24px rgba(0,0,0,.08)",border:`1px solid ${C.border}`,display:"flex",flexDirection:"column",alignItems:"center",boxSizing:"border-box"}}>
        <img src={logoAcierto} alt="Acierto" style={{width:120,maxWidth:"60%",borderRadius:8,display:"block",marginBottom:14}}/>
        <div style={{fontSize:14,color:C.textSec,marginBottom:22,textAlign:"center"}}>Inicia sesión para continuar</div>
        <div style={{marginBottom:14,width:"100%"}}>
          <label htmlFor="login-rfc" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>RFC o USUARIO</label>
          {/* fontSize:16 en los inputs a proposito - por debajo de eso, Safari
              en iOS hace zoom automatico al enfocar el campo. Acepta RFC
              (13 caracteres) O el usuario alterno (6-10) - mismo campo,
              backend decide cual es (ver useAuth.login). Cuentas viejas sin
              usuario siguen entrando igual con su RFC, sin friccion. */}
          <input id="login-rfc" type="text" required autoFocus maxLength={13} value={identificador}
            onChange={e=>setIdentificador(e.target.value.toUpperCase())} placeholder="RFC o USUARIO"
            style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
        </div>
        <div style={{marginBottom:10,width:"100%"}}>
          <label htmlFor="login-password" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>Contraseña</label>
          <input id="login-password" type="password" required value={password} onChange={e=>setPassword(e.target.value)}
            style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
        </div>
        <button type="button" onClick={onIrAOlvide} style={{alignSelf:"flex-end",marginBottom:16,background:"none",border:"none",color:C.textSec,fontSize:12,cursor:"pointer",textDecoration:"underline"}}>
          ¿Olvidaste tu contraseña?
        </button>
        {error && <div style={{fontSize:12,color:C.danger,marginBottom:14,padding:"8px 10px",background:C.dangerSoft,borderRadius:6,width:"100%",boxSizing:"border-box"}}>⚠ {error}</div>}
        <Btn style={{width:"100%",padding:"12px 18px"}} disabled={loading}>{loading ? "Ingresando…" : "Iniciar sesión"}</Btn>
        <button type="button" onClick={onIrARegistro} style={{marginTop:14,background:"none",border:"none",color:C.textSec,fontSize:12,cursor:"pointer",textDecoration:"underline"}}>
          ¿No tienes cuenta? Crear una
        </button>
      </form>
    </div>
  );
}

function OlvideContrasena({ onSolicitar, onIrALogin }) {
  const [email, setEmail] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [enviado, setEnviado] = useState(false);

  const submit = async e => {
    e.preventDefault();
    setLoading(true); setError(null);
    const r = await onSolicitar(email);
    setLoading(false);
    // Mensaje generico SIEMPRE que la llamada responda ok, sin importar si
    // el correo existe o no (el backend ya garantiza la misma respuesta en
    // ambos casos - este componente no distingue nada, solo la muestra).
    if (r.ok) setEnviado(true); else setError(r.error);
  };

  return (
    <div style={{minHeight:"100dvh",display:"flex",alignItems:"center",justifyContent:"center",background:C.surface,padding:20,boxSizing:"border-box"}}>
      <div style={{background:C.card,padding:"28px 22px",borderRadius:12,width:340,maxWidth:"100%",boxShadow:"0 4px 24px rgba(0,0,0,.08)",border:`1px solid ${C.border}`,display:"flex",flexDirection:"column",alignItems:"center",boxSizing:"border-box"}}>
        <img src={logoAcierto} alt="Acierto" style={{width:120,maxWidth:"60%",borderRadius:8,display:"block",marginBottom:14}}/>
        {enviado ? (
          <>
            <div style={{fontSize:14,color:C.text,marginBottom:22,textAlign:"center",lineHeight:1.5}}>
              Si <strong>{email}</strong> está registrado, te enviamos un enlace para recuperar tu contraseña. Revisa tu bandeja de entrada (y spam).
            </div>
            <button type="button" onClick={onIrALogin} style={{background:"none",border:"none",color:C.textSec,fontSize:12,cursor:"pointer",textDecoration:"underline"}}>
              Volver a iniciar sesión
            </button>
          </>
        ) : (
          <form onSubmit={submit} style={{width:"100%",display:"flex",flexDirection:"column",alignItems:"center"}}>
            <div style={{fontSize:14,color:C.textSec,marginBottom:22,textAlign:"center"}}>¿Olvidaste tu contraseña? Escribe tu correo y te mandamos un enlace para recuperarla.</div>
            <div style={{marginBottom:20,width:"100%"}}>
              <label htmlFor="olvide-email" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>Correo electrónico</label>
              <input id="olvide-email" type="email" required autoFocus value={email} onChange={e=>setEmail(e.target.value)}
                style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
            </div>
            {error && <div style={{fontSize:12,color:C.danger,marginBottom:14,padding:"8px 10px",background:C.dangerSoft,borderRadius:6,width:"100%",boxSizing:"border-box"}}>⚠ {error}</div>}
            <Btn style={{width:"100%",padding:"12px 18px"}} disabled={loading}>{loading ? "Enviando…" : "Enviar enlace"}</Btn>
            <button type="button" onClick={onIrALogin} style={{marginTop:14,background:"none",border:"none",color:C.textSec,fontSize:12,cursor:"pointer",textDecoration:"underline"}}>
              Volver a iniciar sesión
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

function ResetPassword({ token, onConfirmar, onIrALogin }) {
  const [password, setPassword] = useState("");
  const [confirmacion, setConfirmacion] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [exito, setExito] = useState(false);

  const submit = async e => {
    e.preventDefault();
    setError(null);
    if (password !== confirmacion) { setError("Las contraseñas no coinciden"); return; }
    setLoading(true);
    const r = await onConfirmar(token, password);
    setLoading(false);
    if (r.ok) setExito(true); else setError(r.error);
  };

  return (
    <div style={{minHeight:"100dvh",display:"flex",alignItems:"center",justifyContent:"center",background:C.surface,padding:20,boxSizing:"border-box"}}>
      <div style={{background:C.card,padding:"28px 22px",borderRadius:12,width:340,maxWidth:"100%",boxShadow:"0 4px 24px rgba(0,0,0,.08)",border:`1px solid ${C.border}`,display:"flex",flexDirection:"column",alignItems:"center",boxSizing:"border-box"}}>
        <img src={logoAcierto} alt="Acierto" style={{width:120,maxWidth:"60%",borderRadius:8,display:"block",marginBottom:14}}/>
        {exito ? (
          <>
            <div style={{fontSize:14,color:C.text,marginBottom:22,textAlign:"center"}}>Tu contraseña se actualizó correctamente.</div>
            <Btn style={{width:"100%",padding:"12px 18px"}} onClick={onIrALogin}>Iniciar sesión</Btn>
          </>
        ) : (
          <form onSubmit={submit} style={{width:"100%",display:"flex",flexDirection:"column",alignItems:"center"}}>
            <div style={{fontSize:14,color:C.textSec,marginBottom:22,textAlign:"center"}}>Escribe tu nueva contraseña</div>
            <div style={{marginBottom:14,width:"100%"}}>
              <label htmlFor="reset-password" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>Nueva contraseña</label>
              <input id="reset-password" type="password" required minLength={8} autoFocus value={password} onChange={e=>setPassword(e.target.value)}
                style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
            </div>
            <div style={{marginBottom:20,width:"100%"}}>
              <label htmlFor="reset-password-confirm" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>Confirmar contraseña</label>
              <input id="reset-password-confirm" type="password" required minLength={8} value={confirmacion} onChange={e=>setConfirmacion(e.target.value)}
                style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
            </div>
            {error && <div style={{fontSize:12,color:C.danger,marginBottom:14,padding:"8px 10px",background:C.dangerSoft,borderRadius:6,width:"100%",boxSizing:"border-box"}}>⚠ {error}</div>}
            <Btn style={{width:"100%",padding:"12px 18px"}} disabled={loading}>{loading ? "Guardando…" : "Cambiar contraseña"}</Btn>
            <button type="button" onClick={onIrALogin} style={{marginTop:14,background:"none",border:"none",color:C.textSec,fontSize:12,cursor:"pointer",textDecoration:"underline"}}>
              Volver a iniciar sesión
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

function CrearCuenta({ onRegistro, onIrALogin }) {
  const [nombreNegocio, setNombreNegocio] = useState("");
  const [nombre, setNombre] = useState("");
  const [email, setEmail] = useState("");
  const [rfcPersonal, setRfcPersonal] = useState("");
  const [usuario, setUsuario] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const submit = async e => {
    e.preventDefault();
    setLoading(true); setError(null);
    const r = await onRegistro(nombreNegocio, email, rfcPersonal, password, nombre, usuario);
    setLoading(false);
    if (!r.ok) setError(r.error);
  };

  return (
    <div style={{minHeight:"100dvh",display:"flex",alignItems:"center",justifyContent:"center",background:C.surface,padding:20,boxSizing:"border-box"}}>
      <form onSubmit={submit} style={{background:C.card,padding:"28px 22px",borderRadius:12,width:340,maxWidth:"100%",boxShadow:"0 4px 24px rgba(0,0,0,.08)",border:`1px solid ${C.border}`,display:"flex",flexDirection:"column",alignItems:"center",boxSizing:"border-box"}}>
        <img src={logoAcierto} alt="Acierto" style={{width:120,maxWidth:"60%",borderRadius:8,display:"block",marginBottom:14}}/>
        <div style={{fontSize:14,color:C.textSec,marginBottom:22,textAlign:"center"}}>Crea tu cuenta</div>
        <div style={{marginBottom:14,width:"100%"}}>
          <label htmlFor="reg-negocio" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>Nombre del negocio</label>
          <input id="reg-negocio" type="text" required autoFocus value={nombreNegocio} onChange={e=>setNombreNegocio(e.target.value)}
            style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
        </div>
        <div style={{marginBottom:14,width:"100%"}}>
          <label htmlFor="reg-nombre" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>Tu nombre</label>
          <input id="reg-nombre" type="text" required value={nombre} onChange={e=>setNombre(e.target.value)}
            style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
        </div>
        <div style={{marginBottom:14,width:"100%"}}>
          <label htmlFor="reg-email" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>Email</label>
          <input id="reg-email" type="email" required value={email} onChange={e=>setEmail(e.target.value)}
            style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
        </div>
        <div style={{marginBottom:14,width:"100%"}}>
          <label htmlFor="reg-rfc" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>RFC</label>
          <input id="reg-rfc" type="text" required maxLength={13} value={rfcPersonal}
            onChange={e=>setRfcPersonal(e.target.value.toUpperCase())} placeholder="AAAA000101AAA"
            style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
        </div>
        <div style={{marginBottom:14,width:"100%"}}>
          <label htmlFor="reg-usuario" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>Usuario</label>
          {/* Credencial alterna al RFC para iniciar sesion despues (ver
              Login) - mismo patron toUpperCase() que el campo RFC de arriba,
              independiente de si el teclado esta en mayus/minus. */}
          <input id="reg-usuario" type="text" required minLength={6} maxLength={10} value={usuario}
            onChange={e=>setUsuario(e.target.value.toUpperCase())} placeholder="6-10 caracteres"
            style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
        </div>
        <div style={{marginBottom:20,width:"100%"}}>
          <label htmlFor="reg-password" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>Contraseña</label>
          <input id="reg-password" type="password" required minLength={8} value={password} onChange={e=>setPassword(e.target.value)}
            style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
        </div>
        {error && <div style={{fontSize:12,color:C.danger,marginBottom:14,padding:"8px 10px",background:C.dangerSoft,borderRadius:6,width:"100%",boxSizing:"border-box"}}>⚠ {error}</div>}
        <Btn style={{width:"100%",padding:"12px 18px"}} disabled={loading}>{loading ? "Creando cuenta…" : "Crear cuenta"}</Btn>
        <button type="button" onClick={onIrALogin} style={{marginTop:14,background:"none",border:"none",color:C.textSec,fontSize:12,cursor:"pointer",textDecoration:"underline"}}>
          ¿Ya tienes cuenta? Inicia sesión
        </button>
      </form>
    </div>
  );
}

function useDocumentExtractor() {
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

function useFiscalChat() {
  const [messages,  setMessages]  = useState([]);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef(null);
  const send = useCallback(async (text, ctx = {}) => {
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
      const res = await fetchAuth(`${API_BASE}/ia/chat/stream`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        signal:abortRef.current.signal,
        body: JSON.stringify({ messages:history, contexto_cuenta:ctx }),
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

function useFacturas(emisorRfc) {
  const [facturas, setFacturas] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      // emisorRfc opcional (#soporte multi-emisor) - sin el, comportamiento
      // identico al de siempre (todas las facturas del negocio). Se agrega
      // a las dependencias del useCallback a proposito: si cambia (ej. el
      // usuario cambia de emisor activo en el header/Emisores), cargar()
      // cambia de identidad y el useEffect de abajo vuelve a disparar el
      // fetch con el nuevo filtro.
      const url = emisorRfc ? `${API_BASE}/facturas?emisor_rfc=${encodeURIComponent(emisorRfc)}` : `${API_BASE}/facturas`;
      const res = await fetchAuth(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setFacturas(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [emisorRfc]);
  useEffect(() => { cargar(); }, [cargar]);
  return { facturas, loading, error, recargar: cargar };
}

function useCostosResumen(emisorRfc) {
  const [datos,   setDatos]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      // emisorRfc opcional (#soporte multi-emisor, mismo patron que
      // useFacturas) - el backend ya filtra por negocio de todos modos
      // (fix critico de aislamiento), esto es solo para el desglose del
      // emisor activo especifico cuando el negocio tiene varios.
      const url = emisorRfc ? `${API_BASE}/facturas/costos-resumen?emisor_rfc=${encodeURIComponent(emisorRfc)}` : `${API_BASE}/facturas/costos-resumen`;
      const res = await fetchAuth(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDatos(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [emisorRfc]);
  useEffect(() => { cargar(); }, [cargar]);
  return { datos, loading, error, recargar: cargar };
}

// Un solo emisor registrado hoy en administración (no hay multi-tenant/login
// todavia) — se usa el primero de la lista como "el" emisor de la cuenta.
const EmisoresContext = createContext(null);

function EmisoresProvider({ children }) {
  const [emisores, setEmisores] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);
  // Soporte multi-emisor (aun sin UI para cambiarlo a mano, ver tarjeta de
  // seguimiento) - "cual emisor esta activo" en la cuenta. Auto-seleccion
  // via setEmisorActivoRfc(prev => ...) (forma funcional, no lee
  // emisorActivoRfc por closure) a proposito: mantiene cargar() con
  // identidad estable entre renders, sin agregar emisorActivoRfc a sus
  // dependencias - si no, cada cambio de emisorActivoRfc recrearia cargar
  // y el useEffect de abajo volveria a disparar el fetch, un loop inutil.
  const [emisorActivoRfc, setEmisorActivoRfc] = useState(null);
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await fetchAuth(`${API_BASE}/admin/emisores`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setEmisores(data);
      // Si ya habia un activo y sigue en la lista nueva, se respeta -
      // si no (primera carga, o ese emisor ya no existe), cae al primero.
      // Con un solo emisor (caso de hoy) esto siempre resuelve al mismo
      // rfc, sin cambio de comportamiento visible.
      setEmisorActivoRfc(prev => (prev && data.some(e => e.rfc === prev)) ? prev : (data[0]?.rfc ?? null));
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { cargar(); }, [cargar]);
  return (
    <EmisoresContext.Provider value={{ emisores, loading, error, recargar: cargar, emisorActivoRfc, setEmisorActivoRfc }}>
      {children}
    </EmisoresContext.Provider>
  );
}

// Antes: cada componente que llamaba useEmisores() disparaba su propio
// fetch a /admin/emisores (hasta 5 llamadas redundantes por carga de app,
// una por NuevaFactura/ChatFiscal/Emisores/ContadorVirtual/AppShell) y el
// header no se enteraba cuando Emisores() creaba un emisor nuevo, porque
// cada uno tenia su propio estado aislado. Ahora useEmisores() consume un
// solo EmisoresContext (provisto en AuthGate, ver mas abajo) - un fetch,
// estado compartido, recargar() de cualquiera actualiza a todos.
function useEmisores() {
  const ctx = useContext(EmisoresContext);
  if (!ctx) throw new Error("useEmisores() debe usarse dentro de <EmisoresProvider>");
  return ctx;
}

function useContadorVirtualISRResico(emisorRfc, anio, mes) {
  const [datos,   setDatos]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  useEffect(() => {
    if (!emisorRfc) { setLoading(false); return; }
    (async () => {
      setLoading(true); setError(null);
      try {
        const params = new URLSearchParams({ emisor_rfc: emisorRfc, anio: String(anio), mes: String(mes) });
        const res = await fetchAuth(`${API_BASE}/facturas/contador-virtual/isr-resico?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setDatos(await res.json());
      } catch (e) { setError(e.message); }
      finally { setLoading(false); }
    })();
  }, [emisorRfc, anio, mes]);
  return { datos, loading, error };
}

function useSeries() {
  const [series,  setSeries]  = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  useEffect(() => {
    (async () => {
      try {
        const res = await fetchAuth(`${API_BASE}/admin/series`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setSeries(await res.json());
      } catch (e) { setError(e.message); }
      finally { setLoading(false); }
    })();
  }, []);
  return { series, loading, error };
}

function useUsuarios() {
  const [usuarios, setUsuarios] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);
  useEffect(() => {
    (async () => {
      try {
        const res = await fetchAuth(`${API_BASE}/auth/usuarios`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setUsuarios(await res.json());
      } catch (e) { setError(e.message); }
      finally { setLoading(false); }
    })();
  }, []);
  return { usuarios, loading, error };
}

function useClientes() {
  const [clientes, setClientes] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);
  useEffect(() => {
    (async () => {
      try {
        const res = await fetchAuth(`${API_BASE}/admin/clientes`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setClientes(await res.json());
      } catch (e) { setError(e.message); }
      finally { setLoading(false); }
    })();
  }, []);
  return { clientes, loading, error };
}

function useResumenEjecutivo() {
  const [resultado, setResultado] = useState(null);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState(null);
  const generar = useCallback(async (payload) => {
    setLoading(true); setError(null); setResultado(null);
    try {
      const res = await fetchAuth(`${API_BASE}/ia/resumen-ejecutivo`, {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP ${res.status}`);
      }
      setResultado(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  return { resultado, generar, loading, error };
}

function useAnomalias() {
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

// ═══════════════════════════════════════════════════════════════════════════════
// TOKENS & DATA
// ═══════════════════════════════════════════════════════════════════════════════
const C = {
  primary:"#0A2540", accent:"#00C896", accentSoft:"#E6FAF5", accentBorder:"#00A87E",
  surface:"#F7F9FC", card:"#FFFFFF", border:"#E4E9F0",
  text:"#0A2540", textSec:"#5A6B7E", textMuted:"#8A9BB0",
  danger:"#E53E3E", dangerSoft:"#FFF5F5", warn:"#DD6B20", warnSoft:"#FFFAF0",
  info:"#2B6CB0", infoSoft:"#EBF8FF",
};
const fmt = n => new Intl.NumberFormat("es-MX",{style:"currency",currency:"MXN"}).format(n);
// FastAPI/Pydantic manda detail como string (400/409) o como arreglo de
// errores de validacion (422) - normaliza ambos a un mensaje legible.
const detalleError = (data, res) => Array.isArray(data.detail)
  ? data.detail.map(d => d.msg || JSON.stringify(d)).join(", ")
  : (data.detail || `HTTP ${res.status}`);

const FACTURAS = [
  {folio:"A-0127",receptor:"Coppel SA de CV",total:77600,fecha:"2025-05-19",estado:"Vigente",uuid:"WXY7-ZAB8"},
  {folio:"A-0126",receptor:"OXXO Gas SA de CV",total:32100,fecha:"2025-05-16",estado:"Vigente",uuid:"KLM3-NOP4"},
  {folio:"A-0041",receptor:"Walmart de México",total:89300,fecha:"2025-05-12",estado:"Alerta",uuid:"MNO5-PQR6"},
  {folio:"A-0039",receptor:"FEMSA",total:124750,fecha:"2025-03-14",estado:"Vencida",uuid:"ABC1-DEF2"},
  {folio:"A-0003",receptor:"Tiendas Chedraui",total:9800,fecha:"2025-05-14",estado:"Cancelada",uuid:"YZA9-BCD0"},
];
const CUENTA_CTX = {iva_pendiente:38640,facturas_vigentes:4,facturas_vencidas:1,total_mayo:302450,cuentas_por_cobrar:246150,proximo_vencimiento_iva:"2025-06-17"};
const NAV = [
  {id:"facturas",label:"Mis Facturas",icon:"📄",children:["nueva","generadas","recibidas","reporte","costos","contador"]},
  {id:"ia",label:"IA",icon:"🤖",children:["lector","chat","anomalias","conciliacion"]},
  {id:"admin",label:"Administración",icon:"⚙️",children:["emisores","clientes","usuarios","series"]},
  {id:"addenda",label:"Addenda AES",icon:"🔗",children:[]},
];
const LABELS = {
  nueva:"Nueva Factura",generadas:"Generadas",recibidas:"Recibidas",reporte:"Reporte Mensual",costos:"Dashboard de Costos",contador:"Contador Virtual",
  lector:"Lector de Documentos",chat:"Chat Fiscal",anomalias:"Anomalías IA",conciliacion:"Conciliación",
  emisores:"Emisores",clientes:"Clientes",usuarios:"Usuarios",series:"Series",addenda:"Addenda AES",
};
const SUGERENCIAS = [
  "¿Cuánto IVA tengo pendiente?","¿Qué clientes tienen RFC en riesgo?",
  "¿Cuánto me deben mis clientes?","Resumen ejecutivo de mayo",
];

// ═══════════════════════════════════════════════════════════════════════════════
// ATOMS
// ═══════════════════════════════════════════════════════════════════════════════
function Badge({estado}){
  const map={Vigente:{bg:"#E6FAF5",c:"#0A6B4A"},Vencida:{bg:"#FFF5F5",c:"#9B2C2C"},
    Cancelada:{bg:"#FFF5F5",c:"#9B2C2C"},Pendiente:{bg:"#FFFAF0",c:"#744210"},Alerta:{bg:"#FFFAF0",c:"#744210"}};
  const s=map[estado]||map.Pendiente;
  return <span style={{background:s.bg,color:s.c,fontSize:11,fontWeight:600,padding:"3px 10px",borderRadius:20,whiteSpace:"nowrap"}}>{estado}</span>;
}
function Card({children,style={},onClick}){
  return <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,padding:16,minWidth:0,maxWidth:"100%",boxSizing:"border-box",...style}} onClick={onClick}>{children}</div>;
}
function Btn({children,variant="primary",onClick,style={},disabled,type="submit"}){
  const base={borderRadius:8,padding:"10px 18px",fontSize:13,fontWeight:600,cursor:disabled?"not-allowed":"pointer",border:"none",opacity:disabled?.5:1,...style};
  const s={primary:{...base,background:C.primary,color:C.accent},secondary:{...base,background:"transparent",color:C.textSec,border:`1px solid ${C.border}`},accent:{...base,background:C.accent,color:"#fff"}};
  return <button type={type} style={s[variant]||s.primary} onClick={disabled?undefined:onClick}>{children}</button>;
}
function SectionTitle({children}){return <h2 style={{fontSize:20,fontWeight:700,color:C.text,marginBottom:4}}>{children}</h2>;}
function SectionSub({children}){return <p style={{color:C.textSec,fontSize:13,marginBottom:18,marginTop:2}}>{children}</p>;}
function TwoCol({children,minCol=260}){return <div style={{display:"grid",gridTemplateColumns:`repeat(auto-fit,minmax(${minCol}px,1fr))`,gap:12,minWidth:0,width:"100%"}}>{children}</div>;}
function KPIGrid({children}){return <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(120px,1fr))",gap:10,marginBottom:16,minWidth:0,width:"100%"}}>{children}</div>;}
function KPI({label,value,sub,dark}){
  return (
    <div style={{background:dark?C.primary:C.card,border:`1px solid ${dark?"transparent":C.border}`,borderRadius:12,padding:"14px 14px",minWidth:0,maxWidth:"100%",boxSizing:"border-box"}}>
      <div style={{fontSize:10,color:dark?"rgba(255,255,255,.5)":C.textMuted,marginBottom:5,textTransform:"uppercase",letterSpacing:"0.06em",overflowWrap:"anywhere",wordBreak:"break-word",whiteSpace:"normal"}}>{label}</div>
      <div style={{fontSize:22,fontWeight:700,color:dark?C.accent:C.text,lineHeight:1,overflowWrap:"anywhere",wordBreak:"break-word",whiteSpace:"nowrap"}}>{value}</div>
      {sub&&<div style={{fontSize:11,color:dark?"rgba(255,255,255,.4)":C.textMuted,marginTop:3}}>{sub}</div>}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: NUEVA FACTURA
// ═══════════════════════════════════════════════════════════════════════════════
function NuevaFactura(){
  const toast = useToast();
  const { emisores, loading:loadingEmisores, error:errorEmisores, emisorActivoRfc } = useEmisores();
  const { clientes, loading:loadingClientes, error:errorClientes } = useClientes();
  // emisorActivoRfc puede ser null (negocio sin ningun emisor) - find()
  // sobre [] o sin match devuelve undefined igual que emisores[0] en ese
  // caso, mismo placeholder/mensaje de "sin emisor" que ya existia.
  const emisor = emisores.find(e=>e.rfc===emisorActivoRfc);

  const [form,setForm]=useState({clienteRfc:"",receptor:"",rfc:"",usoCfdi:"G03",domicilioFiscal:"",regimenFiscal:"",concepto:"",cantidad:"",precio:"",iva:"16"});
  const [enviando,setEnviando]=useState(false);
  const [resultado,setResultado]=useState(null);
  const [errorTimbrado,setErrorTimbrado]=useState(null);

  const sub=(parseFloat(form.cantidad)||0)*(parseFloat(form.precio)||0);
  const total=sub*(1+(parseFloat(form.iva)||0)/100);

  const seleccionarCliente = rfc => {
    setResultado(null); setErrorTimbrado(null);
    if (!rfc) { setForm(f=>({...f,clienteRfc:"",receptor:"",rfc:"",domicilioFiscal:"",regimenFiscal:""})); return; }
    const c = clientes.find(c=>c.rfc===rfc);
    if (!c) return;
    setForm(f=>({...f,clienteRfc:rfc,receptor:c.nombre,rfc:c.rfc,usoCfdi:c.uso_cfdi_default||f.usoCfdi,domicilioFiscal:c.domicilio_fiscal||"",regimenFiscal:c.regimen_fiscal||""}));
  };

  const inp=(lbl,k,type="text")=>(
    <div style={{marginBottom:10}}>
      <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>{lbl}</label>
      <input type={type} value={form[k]} onChange={e=>setForm({...form,[k]:e.target.value})} placeholder={lbl}
        style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}/>
    </div>
  );

  const timbrar = async () => {
    if (!emisor) { toast("No hay ningún emisor registrado en Administración todavía","error"); return; }
    if (!form.receptor||!form.rfc||!form.domicilioFiscal||!form.concepto||!form.cantidad||!form.precio) {
      toast("Completa receptor, domicilio fiscal y los datos del concepto antes de timbrar","warning"); return;
    }
    setEnviando(true); setErrorTimbrado(null); setResultado(null);
    const payload = {
      emisor_rfc: emisor.rfc,
      receptor: {
        nombre: form.receptor,
        rfc: form.rfc,
        uso_cfdi: form.usoCfdi,
        domicilio_fiscal: form.domicilioFiscal,
        ...(form.regimenFiscal ? { regimen_fiscal: form.regimenFiscal } : {}),
      },
      conceptos: [{
        descripcion: form.concepto,
        cantidad: parseFloat(form.cantidad),
        precio_unitario: parseFloat(form.precio),
        iva_tasa: (parseFloat(form.iva)||0)/100,
      }],
    };
    try {
      const res = await fetchAuth(`${API_BASE}/facturas/timbrar`, {
        method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload),
      });
      const data = await res.json().catch(()=>({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setResultado(data);
      toast(`Factura timbrada — UUID ${data.uuid}`,"success");
    } catch(e) {
      setErrorTimbrado(e.message);
      toast(`Error al timbrar: ${e.message}`,"error");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div>
      <SectionTitle>Nueva Factura CFDI 4.0</SectionTitle>
      <SectionSub>O usa el <strong>Lector IA</strong> para subir una orden de compra y rellenar automáticamente.</SectionSub>
      <TwoCol>
        <Card>
          <div style={{fontSize:11,fontWeight:700,color:C.accent,letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>Emisor</div>
          {loadingEmisores && <div style={{fontSize:13,color:C.textMuted}}>Cargando emisor…</div>}
          {errorEmisores && <div style={{fontSize:13,color:C.danger}}>⚠ No se pudo cargar el emisor: {errorEmisores}</div>}
          {!loadingEmisores && !errorEmisores && !emisor && (
            <div style={{fontSize:13,color:C.warn}}>No hay emisores registrados en Administración.</div>
          )}
          {emisor && [["Razón social",emisor.razon_social],["RFC",emisor.rfc],["Régimen fiscal",emisor.regimen_fiscal],["CP",emisor.codigo_postal]].map(([l,v])=>(
            <div key={l} style={{marginBottom:10}}>
              <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>{l}</label>
              <input readOnly value={v} style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:C.surface,boxSizing:"border-box"}}/>
            </div>
          ))}
        </Card>
        <Card>
          <div style={{fontSize:11,fontWeight:700,color:C.accent,letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>Receptor</div>
          <div style={{marginBottom:10}}>
            <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Cliente registrado</label>
            <select value={form.clienteRfc} onChange={e=>seleccionarCliente(e.target.value)} disabled={loadingClientes}
              style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}>
              <option value="">— Receptor nuevo (captura manual) —</option>
              {clientes.map(c=>(<option key={c.rfc} value={c.rfc}>{c.nombre} — {c.rfc}</option>))}
            </select>
            {errorClientes && <div style={{fontSize:11,color:C.danger,marginTop:4}}>⚠ No se pudieron cargar los clientes: {errorClientes}</div>}
          </div>
          {inp("Nombre / Razón social","receptor")}
          {inp("RFC","rfc")}
          {inp("Domicilio fiscal (CP)","domicilioFiscal")}
          <div style={{marginBottom:10}}>
            <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Uso CFDI</label>
            <select value={form.usoCfdi} onChange={e=>setForm({...form,usoCfdi:e.target.value})}
              style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}>
              <option value="G03">G03 – Gastos en general</option><option value="G01">G01 – Adquisición de mercancías</option><option value="S01">S01 – Sin efectos fiscales</option>
            </select>
          </div>
        </Card>
      </TwoCol>
      <Card style={{marginTop:12}}>
        <div style={{fontSize:11,fontWeight:700,color:C.accent,letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>Conceptos</div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(130px,1fr))",gap:10,marginBottom:10}}>
          {inp("Descripción","concepto")}
          {inp("Cantidad","cantidad","number")}
          {inp("Precio unitario","precio","number")}
          {inp("IVA %","iva","number")}
        </div>
        <div style={{display:"flex",justifyContent:"flex-end",gap:20,paddingTop:12,borderTop:`1px solid ${C.border}`,flexWrap:"wrap"}}>
          {[["Subtotal",sub],["IVA",sub*(parseFloat(form.iva)||0)/100],["Total",total]].map(([l,v])=>(
            <div key={l} style={{textAlign:"right"}}>
              <div style={{fontSize:11,color:C.textMuted}}>{l}</div>
              <div style={{fontSize:l==="Total"?18:13,fontWeight:l==="Total"?700:500,color:l==="Total"?C.accent:C.text}}>{fmt(v)}</div>
            </div>
          ))}
        </div>
      </Card>
      <div style={{marginTop:12,display:"flex",gap:10,flexWrap:"wrap"}}>
        <Btn onClick={timbrar} disabled={enviando}>{enviando?"Timbrando…":"Timbrar con PAC →"}</Btn>
        <Btn variant="secondary" onClick={()=>toast("Borrador guardado localmente","success")}>Guardar borrador</Btn>
      </div>
      {errorTimbrado && (
        <Card style={{marginTop:12,borderColor:C.danger,background:C.dangerSoft}}>
          <div style={{fontSize:13,color:C.danger}}>⚠ {errorTimbrado}</div>
        </Card>
      )}
      {resultado && (
        <Card style={{marginTop:12,borderColor:C.accentBorder,background:C.accentSoft}}>
          <div style={{fontSize:11,fontWeight:700,color:"#0A6B4A",letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>✓ Timbrado exitoso</div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10,marginBottom:12}}>
            {[["UUID",resultado.uuid],["Folio",resultado.folio],["Estado",resultado.estado],["Total",fmt(resultado.total)]].map(([l,v])=>(
              <div key={l} style={{background:"#fff",borderRadius:8,padding:"10px 12px"}}>
                <div style={{fontSize:10,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",marginBottom:3}}>{l}</div>
                <div style={{fontSize:13,fontWeight:600,color:C.text,wordBreak:"break-all"}}>{v}</div>
              </div>
            ))}
          </div>
          <div style={{display:"flex",gap:10,flexWrap:"wrap"}}>
            <a href={resultado.xml_url} target="_blank" rel="noreferrer"><Btn variant="secondary">Descargar XML</Btn></a>
            <a href={resultado.pdf_url} target="_blank" rel="noreferrer"><Btn variant="secondary">Descargar PDF</Btn></a>
          </div>
          <div style={{fontSize:11,color:C.textMuted,marginTop:8}}>
            Nota: las URLs de descarga apuntan a MinIO dentro de la red de Docker — hoy no son accesibles desde fuera de ese entorno (ver #8/#19/#20).
          </div>
        </Card>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: FACTURAS GENERADAS — tabla compacta con scroll horizontal
// ═══════════════════════════════════════════════════════════════════════════════
function FacturasGeneradas(){
  const {isMobile} = useBreakpoint();
  const toast = useToast();
  const { emisorActivoRfc } = useEmisores();
  const {facturas,loading,error,recargar} = useFacturas(emisorActivoRfc);
  const [q,setQ]=useState("");
  const [filtro,setFiltro]=useState("Todas");
  const items=facturas.filter(f=>(filtro==="Todas"||f.estado===filtro)&&
    (f.receptor_rfc.toLowerCase().includes(q.toLowerCase())||f.folio.includes(q)));

  if (error) return <Placeholder title="Facturas generadas" detail={`No se pudo conectar con facturacion (${FACTURACION_BASE}): ${error}`}/>;

  return (
    <div>
      <SectionTitle>Facturas generadas</SectionTitle>
      <KPIGrid>
        <KPI label="Total emitido" value={fmt(facturas.reduce((s,f)=>s+f.total,0))} dark/>
        <KPI label="Vigentes"   value={facturas.filter(f=>f.estado==="Vigente").length}/>
        <KPI label="Vencidas"   value={facturas.filter(f=>f.estado==="Vencida").length}/>
        <KPI label="Canceladas" value={facturas.filter(f=>f.estado==="Cancelada").length}/>
      </KPIGrid>

      <Card style={{padding:0,overflow:"hidden"}}>
        {/* Barra de búsqueda y filtros */}
        <div style={{padding:"10px 12px",borderBottom:`1px solid ${C.border}`,display:"flex",gap:8,flexWrap:"wrap",alignItems:"center"}}>
          <input value={q} onChange={e=>setQ(e.target.value)} placeholder="Buscar folio o RFC receptor…"
            style={{flex:1,minWidth:100,border:`1px solid ${C.border}`,borderRadius:8,padding:"7px 11px",fontSize:13,color:C.text,background:C.surface}}/>
          <div style={{display:"flex",gap:5,flexWrap:"wrap"}}>
            {["Todas","Vigente","Vencida","Cancelada"].map(f=>(
              <button key={f} onClick={()=>setFiltro(f)}
                style={{fontSize:11,padding:"5px 10px",borderRadius:12,border:`1px solid ${filtro===f?C.accent:C.border}`,
                  background:filtro===f?C.accentSoft:"transparent",color:filtro===f?C.accentBorder:C.textSec,cursor:"pointer",whiteSpace:"nowrap"}}>
                {f}
              </button>
            ))}
          </div>
          <button onClick={recargar} title="Recargar" disabled={loading}
            style={{fontSize:11,padding:"5px 10px",borderRadius:12,border:`1px solid ${C.border}`,background:"transparent",color:C.textSec,cursor:loading?"not-allowed":"pointer"}}>
            {loading?"Cargando…":"↻ Recargar"}
          </button>
        </div>

        {/* Tabla con scroll horizontal */}
        <div style={{overflowX:"auto",WebkitOverflowScrolling:"touch"}}>
          <table style={{width:"100%",borderCollapse:"collapse",minWidth:isMobile?360:540}}>
            <thead>
              <tr style={{background:C.surface}}>
                <th style={TH}>Folio</th>
                <th style={TH}>Receptor (RFC)</th>
                {!isMobile&&<th style={TH}>Fecha timbrado</th>}
                <th style={{...TH,textAlign:"right"}}>Total</th>
                <th style={{...TH,textAlign:"center"}}>Estado</th>
                {!isMobile&&<th style={TH}>Usuario</th>}
                {!isMobile&&<th style={TH}></th>}
              </tr>
            </thead>
            <tbody>
              {!loading && items.length===0 && (
                <tr><td colSpan={isMobile?4:7} style={{...TD,textAlign:"center",color:C.textMuted,padding:"24px 12px"}}>
                  {facturas.length===0 ? "Todavía no hay facturas timbradas." : "Sin resultados para ese filtro/búsqueda."}
                </td></tr>
              )}
              {items.map((f,i)=>(
                <tr key={f.uuid} style={{borderTop:`1px solid ${C.border}`,background:i%2===0?"#fff":C.surface,cursor:"pointer"}}
                  onClick={()=>!isMobile&&toast(`Factura ${f.folio} · UUID: ${f.uuid}`,"info")}>
                  <td style={TD}><span style={{fontFamily:"monospace",fontSize:12,fontWeight:600,color:C.primary}}>{f.folio}</span></td>
                  <td style={{...TD,maxWidth:isMobile?90:180}}><span style={{display:"block",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap",fontSize:13,fontFamily:"monospace"}}>{f.receptor_rfc}</span></td>
                  {!isMobile&&<td style={{...TD,color:C.textSec,fontSize:12,whiteSpace:"nowrap"}}>{new Date(f.fecha_timbrado).toLocaleString("es-MX")}</td>}
                  <td style={{...TD,textAlign:"right",fontWeight:600,fontSize:13,whiteSpace:"nowrap"}}>{fmt(f.total)}</td>
                  <td style={{...TD,textAlign:"center"}}><Badge estado={f.estado}/></td>
                  {!isMobile&&(
                    <td style={{...TD,color:C.textSec,fontSize:12,fontFamily:"monospace",whiteSpace:"nowrap"}}>
                      {(f.estado==="Cancelada" ? f.cancelado_por_rfc : f.creado_por_rfc) || "—"}
                    </td>
                  )}
                  {!isMobile&&(
                    <td style={{...TD,whiteSpace:"nowrap"}} onClick={e=>e.stopPropagation()}>
                      <a href={f.xml_url} target="_blank" rel="noreferrer"
                        style={{fontSize:11,padding:"3px 8px",borderRadius:6,border:`1px solid ${C.border}`,background:"transparent",cursor:"pointer",color:C.textSec,marginRight:4,textDecoration:"none",display:"inline-block"}}>XML</a>
                      <a href={f.pdf_url} target="_blank" rel="noreferrer"
                        style={{fontSize:11,padding:"3px 8px",borderRadius:6,border:`1px solid ${C.border}`,background:"transparent",cursor:"pointer",color:C.textSec,textDecoration:"none",display:"inline-block"}}>PDF</a>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <div style={{fontSize:11,color:C.textMuted,marginTop:8}}>
        Nota: las URLs de descarga apuntan a MinIO dentro de la red de Docker — hoy no son accesibles desde fuera de ese entorno (ver #8/#19/#20).
      </div>
    </div>
  );
}
const TH = {padding:"9px 12px",textAlign:"left",fontSize:10,fontWeight:700,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",whiteSpace:"nowrap"};
const TD = {padding:"10px 12px",color:C.text};

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: LECTOR IA
// ═══════════════════════════════════════════════════════════════════════════════
function LectorDocumentos(){
  const toast = useToast();
  const {extraer,loading,result,error,steps}=useDocumentExtractor();
  const [dragging,setDragging]=useState(false);
  const [file,setFile]=useState(null);
  const inputRef=useRef();
  const handleFile=f=>{setFile(f);extraer(f);};
  const onDrop=e=>{e.preventDefault();setDragging(false);const f=e.dataTransfer.files[0];if(f)handleFile(f);};
  return (
    <div>
      <SectionTitle>Lector de documentos IA</SectionTitle>
      <SectionSub>Sube una orden de compra, cotización o nota — la IA extrae los datos y genera el CFDI.</SectionSub>
      {!file&&(
        <>
          <div onDrop={onDrop} onDragOver={e=>{e.preventDefault();setDragging(true);}} onDragLeave={()=>setDragging(false)}
            onClick={()=>inputRef.current.click()}
            style={{border:`2px dashed ${dragging?C.accent:C.border}`,borderRadius:12,padding:"40px 20px",textAlign:"center",cursor:"pointer",background:dragging?C.accentSoft:"transparent",transition:"all .2s"}}>
            <div style={{fontSize:36,marginBottom:10}}>📄</div>
            <div style={{fontSize:14,fontWeight:600,color:C.text,marginBottom:4}}>Arrastra tu documento aquí</div>
            <div style={{fontSize:12,color:C.textMuted}}>PDF · XML · JPG · PNG</div>
            <input ref={inputRef} type="file" accept=".pdf,.jpg,.jpeg,.png,.xml" style={{display:"none"}} onChange={e=>e.target.files[0]&&handleFile(e.target.files[0])}/>
          </div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(100px,1fr))",gap:8,marginTop:10}}>
            {[["🛒","Orden de compra"],["📋","Cotización"],["🚚","Nota de entrega"]].map(([ic,lbl])=>(
              <div key={lbl} onClick={()=>inputRef.current.click()} style={{background:C.surface,border:`1px solid ${C.border}`,borderRadius:10,padding:"12px 8px",textAlign:"center",cursor:"pointer"}}>
                <div style={{fontSize:22,marginBottom:4}}>{ic}</div>
                <div style={{fontSize:11,color:C.textSec}}>{lbl}</div>
              </div>
            ))}
          </div>
        </>
      )}
      {loading&&(
        <Card style={{marginTop:14}}>
          <div style={{fontSize:12,color:C.textMuted,marginBottom:6}}>{file?.name}</div>
          <div style={{height:4,background:C.surface,borderRadius:2,overflow:"hidden",marginBottom:14}}>
            <div style={{height:"100%",background:C.accent,borderRadius:2,width:`${Math.min((steps.length/4)*100,95)}%`,transition:"width .5s"}}/>
          </div>
          {steps.map((s,i)=>(
            <div key={i} style={{display:"flex",alignItems:"center",gap:10,padding:"7px 0",borderBottom:`1px solid ${C.border}`}}>
              <span style={{color:C.accent}}>✓</span><span style={{fontSize:13,color:C.textSec}}>{s}</span>
            </div>
          ))}
        </Card>
      )}
      {error&&(
        <Card style={{marginTop:14,borderColor:C.danger,background:C.dangerSoft}}>
          <div style={{fontSize:13,color:C.danger}}>⚠ {error}</div>
          <Btn variant="secondary" onClick={()=>setFile(null)} style={{marginTop:10}}>Intentar con otro archivo</Btn>
        </Card>
      )}
      {result&&(
        <div style={{marginTop:14}}>
          <Card>
            <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:14,flexWrap:"wrap",gap:8}}>
              <div style={{fontSize:12,fontWeight:700,color:C.text,textTransform:"uppercase",letterSpacing:"0.06em"}}>Datos extraídos por IA</div>
              <span style={{fontSize:11,fontWeight:600,color:"#0A6B4A"}}>✓ {Math.round((result.confianza?.general||.95)*100)}% confianza</span>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10}}>
              {[["Receptor",result.receptor_nombre],["RFC",result.receptor_rfc],["Uso CFDI",result.receptor_uso_cfdi],["Método pago",result.metodo_pago],["Orden",result.numero_orden],["Addenda",result.addenda_detectada||"—"]].map(([l,v])=>(
                <div key={l} style={{background:C.surface,borderRadius:8,padding:"10px 12px",position:"relative"}}>
                  <div style={{fontSize:10,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",marginBottom:3}}>{l}</div>
                  <div style={{fontSize:13,fontWeight:600,color:C.text}}>{v||"—"}</div>
                  <span style={{position:"absolute",top:8,right:8,fontSize:9,fontWeight:600,padding:"2px 6px",borderRadius:8,background:"#EBF8FF",color:C.info}}>IA</span>
                </div>
              ))}
            </div>
          </Card>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10,marginTop:10}}>
            <Btn onClick={()=>toast(`POST ${API_BASE}/facturas/timbrar — ${result.receptor_nombre}`,"api")}>Timbrar este CFDI →</Btn>
            <Btn variant="secondary" onClick={()=>setFile(null)}>Procesar otro documento</Btn>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: CHAT FISCAL
// ═══════════════════════════════════════════════════════════════════════════════
function ChatFiscal(){
  const {isMobile}=useBreakpoint();
  const {messages,send,streaming,reset,abort}=useFiscalChat();
  const {emisores,emisorActivoRfc}=useEmisores();
  const emisorActual=emisores.find(e=>e.rfc===emisorActivoRfc);
  const [input,setInput]=useState("");
  const bottomRef=useRef();
  useEffect(()=>{bottomRef.current?.scrollIntoView({behavior:"smooth"});},[messages]);
  const submit=()=>{if(!input.trim()||streaming)return;send(input.trim(),CUENTA_CTX);setInput("");};
  return (
    <div style={{display:"flex",flexDirection:"column",height:isMobile?"calc(100dvh - 170px)":"calc(100vh - 155px)",gap:10}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",flexWrap:"wrap",gap:8}}>
        <div><SectionTitle>Chat fiscal IA</SectionTitle><p style={{fontSize:12,color:C.textSec,margin:0}}>Conectado · RFC {emisorActual?.rfc||"—"}</p></div>
        <div style={{display:"flex",gap:8}}>
          {streaming&&<Btn variant="secondary" onClick={abort} style={{fontSize:12,padding:"6px 12px"}}>Detener</Btn>}
          <Btn variant="secondary" onClick={reset} style={{fontSize:12,padding:"6px 12px"}}>Nueva conversación</Btn>
        </div>
      </div>
      <Card style={{flex:1,overflowY:"auto",padding:14,display:"flex",flexDirection:"column",gap:10,minHeight:0}}>
        {messages.length===0&&(
          <div style={{display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",height:"100%",gap:14,padding:"0 10px"}}>
            <div style={{width:48,height:48,borderRadius:14,background:C.primary,display:"flex",alignItems:"center",justifyContent:"center",fontSize:22}}>🤖</div>
            <div style={{fontSize:14,fontWeight:600,color:C.text,textAlign:"center"}}>¿En qué te ayudo hoy?</div>
            <div style={{display:"flex",flexWrap:"wrap",gap:8,justifyContent:"center"}}>
              {SUGERENCIAS.map(s=>(
                <button key={s} onClick={()=>send(s,CUENTA_CTX)}
                  style={{fontSize:12,padding:"7px 12px",borderRadius:20,border:`1px solid ${C.border}`,background:C.surface,color:C.textSec,cursor:"pointer",textAlign:"left"}}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m,i)=>(
          <div key={i} style={{display:"flex",gap:8,justifyContent:m.role==="user"?"flex-end":"flex-start",alignItems:"flex-start"}}>
            {m.role==="assistant"&&<div style={{width:26,height:26,borderRadius:8,background:C.primary,display:"flex",alignItems:"center",justifyContent:"center",fontSize:13,flexShrink:0,marginTop:2}}>🤖</div>}
            <div style={{maxWidth:"82%",padding:"10px 13px",borderRadius:m.role==="user"?"12px 4px 12px 12px":"4px 12px 12px 12px",background:m.role==="user"?C.primary:C.surface,color:m.role==="user"?"#E8F4FF":C.text,fontSize:13,lineHeight:1.6,whiteSpace:"pre-wrap",wordBreak:"break-word"}}>
              {m.content||<span style={{opacity:.4}}>●●●</span>}
            </div>
          </div>
        ))}
        <div ref={bottomRef}/>
      </Card>
      <div style={{display:"flex",gap:8}}>
        <input value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>e.key==="Enter"&&submit()}
          placeholder="Pregunta sobre IVA, clientes, facturas…"
          style={{flex:1,border:`1px solid ${C.border}`,borderRadius:8,padding:"10px 13px",fontSize:13,color:C.text,background:C.card,minWidth:0}}/>
        <Btn onClick={submit} disabled={streaming} style={{padding:"10px 16px",flexShrink:0}}>→</Btn>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: ANOMALÍAS
// ═══════════════════════════════════════════════════════════════════════════════
function Anomalias(){
  const {anomalias,detectar,loading,error}=useAnomalias();
  const [ran,setRan]=useState(false);
  const correr=async()=>{await detectar(FACTURAS,[]);setRan(true);};
  const sevColor={alta:{bg:C.dangerSoft,c:C.danger},media:{bg:C.warnSoft,c:C.warn},baja:{bg:"#EBF8FF",c:C.info}};
  return (
    <div>
      <div style={{display:"flex",alignItems:"flex-start",justifyContent:"space-between",marginBottom:16,gap:12,flexWrap:"wrap"}}>
        <div><SectionTitle>Anomalías IA</SectionTitle><SectionSub>Análisis automático de facturas y pagos en busca de riesgos.</SectionSub></div>
        <Btn onClick={correr} disabled={loading}>{loading?"Analizando…":"Analizar ahora →"}</Btn>
      </div>
      {!ran&&!loading&&!error&&<Card style={{textAlign:"center",padding:48}}><div style={{fontSize:36,marginBottom:10}}>🔍</div><div style={{fontSize:14,fontWeight:600,color:C.text}}>Sin análisis todavía</div></Card>}
      {loading&&<Card style={{textAlign:"center",padding:40}}><div style={{fontSize:13,color:C.textSec}}>⚙️ La IA está revisando tus facturas…</div></Card>}
      {error&&!loading&&<Card style={{borderColor:C.danger,background:C.dangerSoft}}><div style={{fontSize:13,color:C.danger}}>⚠ {error}</div></Card>}
      {ran&&!loading&&!error&&anomalias.length===0&&<Card style={{textAlign:"center",padding:48}}><div style={{fontSize:36,marginBottom:10}}>✅</div><div style={{fontSize:14,fontWeight:600,color:C.text}}>Sin anomalías detectadas</div></Card>}
      {anomalias.map((a,i)=>{
        const s=sevColor[a.severidad]||sevColor.baja;
        return (
          <Card key={i} style={{marginBottom:10,borderLeft:`3px solid ${s.c}`}}>
            <div style={{display:"flex",gap:12,flexWrap:"wrap"}}>
              <div style={{width:34,height:34,borderRadius:8,background:s.bg,display:"flex",alignItems:"center",justifyContent:"center",fontSize:16,flexShrink:0}}>
                {a.tipo==="pago_retrasado"?"⏰":a.tipo==="rfc_riesgo"?"🚫":a.tipo==="discrepancia_pago"?"⚡":"📋"}
              </div>
              <div style={{flex:1,minWidth:0}}>
                <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:4,flexWrap:"wrap"}}>
                  <span style={{fontSize:13,fontWeight:700,color:C.text}}>{a.titulo}</span>
                  <span style={{fontSize:10,fontWeight:600,padding:"2px 8px",borderRadius:10,background:s.bg,color:s.c,whiteSpace:"nowrap"}}>{a.severidad.toUpperCase()}</span>
                </div>
                <div style={{fontSize:13,color:C.textSec,marginBottom:6}}>{a.descripcion}</div>
                <div style={{fontSize:12,color:C.info,background:"#EBF8FF",padding:"6px 10px",borderRadius:6}}>💡 {a.accion_recomendada}</div>
              </div>
              {a.monto_en_riesgo>0&&<div style={{textAlign:"right",flexShrink:0}}><div style={{fontSize:11,color:C.textMuted}}>En riesgo</div><div style={{fontSize:14,fontWeight:700,color:C.danger}}>{fmt(a.monto_en_riesgo)}</div></div>}
            </div>
          </Card>
        );
      })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: CLIENTES
// ═══════════════════════════════════════════════════════════════════════════════
function Clientes(){
  const toast = useToast();
  const {clientes,loading,error} = useClientes();

  if (error) return <Placeholder title="Clientes" detail={`No se pudo conectar con administracion (${ADMINISTRACION_BASE}): ${error}`}/>;
  if (loading) return <Placeholder title="Clientes" detail="Cargando datos reales…"/>;
  if (clientes.length===0) return <Placeholder title="Clientes" detail="Todavía no hay clientes registrados."/>;

  return (
    <div>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:16,flexWrap:"wrap",gap:10}}>
        <SectionTitle>Clientes</SectionTitle>
        <Btn onClick={()=>toast(`POST ${API_BASE}/admin/clientes`,"api")}>+ Nuevo cliente</Btn>
      </div>
      <TwoCol>
        {clientes.map(c=>(
          <Card key={c.rfc}>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10,gap:8}}>
              <div style={{minWidth:0}}>
                <div style={{fontSize:14,fontWeight:600,color:C.text,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{c.nombre}</div>
                <div style={{fontSize:12,color:C.textMuted,fontFamily:"monospace",marginTop:2}}>{c.rfc}</div>
              </div>
              <span style={{background:C.accentSoft,color:C.accentBorder,fontSize:11,fontWeight:600,padding:"3px 10px",borderRadius:20,flexShrink:0}}>Activo</span>
            </div>
            <div style={{fontSize:13,color:C.textSec,marginBottom:6,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>✉ {c.email||"—"}</div>
            <div style={{fontSize:13,color:C.textSec}}>Crédito: <strong style={{color:C.text}}>{fmt(c.credito_limite||0)}</strong></div>
            <div style={{marginTop:12,display:"flex",gap:8,flexWrap:"wrap"}}>
              <button onClick={()=>toast(`PUT ${API_BASE}/admin/clientes/${c.rfc}`,"api")}
                style={{fontSize:12,padding:"6px 12px",borderRadius:7,border:`1px solid ${C.border}`,background:"transparent",cursor:"pointer",color:C.textSec}}>Editar</button>
              <button onClick={()=>toast(`GET ${API_BASE}/facturas?receptor=${c.rfc}`,"api")}
                style={{fontSize:12,padding:"6px 12px",borderRadius:7,border:`1px solid ${C.accentBorder}`,background:C.accentSoft,cursor:"pointer",color:C.accentBorder}}>Ver facturas</button>
            </div>
          </Card>
        ))}
      </TwoCol>
    </div>
  );
}

function AltaEmisorForm({ onCreado, onCancelar }) {
  const toast = useToast();
  const [form, setForm] = useState({ razon_social:"", rfc:"", regimen_fiscal:"", codigo_postal:"", csd_password:"" });
  const [cerFile, setCerFile] = useState(null);
  const [keyFile, setKeyFile] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(null);
  const cerInputRef = useRef();
  const keyInputRef = useRef();

  // Convierte el archivo a lo que EmisorCreate espera (base64 en JSON, no
  // multipart/form-data) - a diferencia del Lector de Documentos IA, que si
  // usa FormData porque su endpoint acepta multipart.
  const fileToBase64 = (file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error("No se pudo leer el archivo"));
    reader.readAsDataURL(file);
  });

  // El CSD y la contrasena nunca deben sobrevivir en memoria del componente
  // mas de lo necesario - se limpian tanto en exito como en cualquier envio,
  // los inputs de archivo se resetean via ref (value de un <input type="file">
  // no se puede controlar por state).
  const limpiarFormulario = () => {
    setForm({ razon_social:"", rfc:"", regimen_fiscal:"", codigo_postal:"", csd_password:"" });
    setCerFile(null); setKeyFile(null);
    if (cerInputRef.current) cerInputRef.current.value = "";
    if (keyInputRef.current) keyInputRef.current.value = "";
  };

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    if (!form.razon_social || !form.rfc || !form.regimen_fiscal || !form.codigo_postal || !form.csd_password) {
      setError("Completa todos los campos antes de continuar."); return;
    }
    if (!cerFile || !keyFile) {
      setError("Sube los dos archivos del CSD (.cer y .key)."); return;
    }
    setEnviando(true);
    try {
      const [csd_cert_base64, csd_key_base64] = await Promise.all([fileToBase64(cerFile), fileToBase64(keyFile)]);
      const res = await fetchAuth(`${API_BASE}/admin/emisores`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          razon_social: form.razon_social,
          rfc: form.rfc,
          regimen_fiscal: form.regimen_fiscal,
          codigo_postal: form.codigo_postal,
          csd_cert_base64, csd_key_base64,
          csd_password: form.csd_password,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detalleError(data, res));
      toast(`Emisor ${data.rfc} registrado correctamente`, "success");
      limpiarFormulario();
      onCreado();
    } catch (e) {
      setError(e.message);
      toast(`Error al registrar emisor: ${e.message}`, "error");
    } finally {
      setEnviando(false);
    }
  };

  const inp = (lbl, k, opts = {}) => (
    <div style={{marginBottom:12}}>
      <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>{lbl}</label>
      <input type={opts.type||"text"} value={form[k]} maxLength={opts.maxLength} autoComplete="off"
        onChange={e=>setForm({...form,[k]: opts.upper ? e.target.value.toUpperCase() : e.target.value})}
        placeholder={opts.placeholder||lbl}
        style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}/>
    </div>
  );

  return (
    <div>
      <SectionTitle>Emisores</SectionTitle>
      <SectionSub>{onCancelar ? "Registra los datos y el CSD del nuevo emisor." : "Todavía no hay ningún emisor registrado — da de alta el primero para poder timbrar."}</SectionSub>
      <Card style={{maxWidth:480}}>
        {/* autoComplete="off" en el <form> (algunos navegadores lo respetan a
            nivel de formulario completo) + en cada input individual, porque
            Chrome moderno frecuentemente lo ignora campo por campo. La
            contrasena del CSD usa "new-password" en vez de "off" - es la
            unica senal que Chrome respeta de forma confiable para no
            ofrecer autocompletar ahi con una contrasena guardada de otro
            sitio (ver hallazgo real de "RAHP7" autocompletado en CP). */}
        <form onSubmit={submit} autoComplete="off">
          {inp("Razón social","razon_social")}
          {inp("RFC","rfc",{upper:true,maxLength:13,placeholder:"AAAA000101AAA"})}
          {inp("Régimen fiscal (código SAT)","regimen_fiscal",{maxLength:3,placeholder:"601"})}
          {inp("Código postal de expedición","codigo_postal",{maxLength:5,placeholder:"00000"})}

          <div style={{marginBottom:12}}>
            <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Certificado (.cer)</label>
            <input ref={cerInputRef} type="file" accept=".cer" autoComplete="off" onChange={e=>setCerFile(e.target.files[0]||null)}
              style={{width:"100%",fontSize:12,color:C.text}}/>
          </div>
          <div style={{marginBottom:12}}>
            <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Llave privada (.key)</label>
            <input ref={keyInputRef} type="file" accept=".key" autoComplete="off" onChange={e=>setKeyFile(e.target.files[0]||null)}
              style={{width:"100%",fontSize:12,color:C.text}}/>
          </div>
          <div style={{marginBottom:16}}>
            <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Contraseña del CSD</label>
            <input type="password" value={form.csd_password} autoComplete="new-password" onChange={e=>setForm({...form,csd_password:e.target.value})}
              style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}/>
          </div>

          {error && <div style={{fontSize:12,color:C.danger,marginBottom:14,padding:"8px 10px",background:C.dangerSoft,borderRadius:6}}>⚠ {error}</div>}

          <div style={{display:"flex",gap:8}}>
            <Btn disabled={enviando} style={{flex:1}}>{enviando?"Registrando…":"Registrar emisor"}</Btn>
            {/* Solo si NO es el primer emisor de todos - sin onCancelar (alta
                inicial obligatoria) no hay a donde volver. type="button" a
                proposito (ver Btn) - sin esto, este boton dispararia el
                submit del form en vez de solo cancelar. */}
            {onCancelar && <Btn type="button" variant="secondary" onClick={onCancelar} disabled={enviando}>Cancelar</Btn>}
          </div>
        </form>
      </Card>
    </div>
  );
}

function Emisores(){
  const {emisores,loading,error,recargar,emisorActivoRfc,setEmisorActivoRfc} = useEmisores();
  // null = "todavia no decidido" - se resuelve una sola vez, la primera vez
  // que loading pasa a false (ver useEffect de abajo). No se puede derivar
  // esto directo como valor inicial de useState(emisores.length===0):
  // useState solo lee su argumento en el PRIMER render, que ocurre mientras
  // loading todavia es true y emisores=[] (estado inicial del Provider) -
  // aunque la cuenta real tenga emisores, ese primer render vería length
  // 0 y decidiria mal, de forma permanente, antes de que el fetch real
  // resolviera. Mismo comportamiento inicial que existia hoy (mostrar
  // AltaEmisorForm solo cuando de verdad no hay ningun emisor), solo que
  // ahora es un estado explicito en vez de un gate directo sobre length,
  // para poder volver a el con "+ Agregar otro emisor".
  const [mostrandoFormulario, setMostrandoFormulario] = useState(null);
  useEffect(() => {
    if (!loading && mostrandoFormulario === null) {
      setMostrandoFormulario(emisores.length === 0);
    }
  }, [loading, emisores, mostrandoFormulario]);

  if (error) return <Placeholder title="Emisores" detail={`No se pudo conectar con administracion (${ADMINISTRACION_BASE}): ${error}`}/>;
  if (loading || mostrandoFormulario === null) return <Placeholder title="Emisores" detail="Cargando datos reales…"/>;

  const haySalidaDeVuelta = emisores.length > 0; // false solo en el alta del primer emisor de todos
  if (mostrandoFormulario) {
    return (
      <AltaEmisorForm
        onCreado={() => { recargar(); setMostrandoFormulario(false); }}
        onCancelar={haySalidaDeVuelta ? () => setMostrandoFormulario(false) : undefined}
      />
    );
  }

  return (
    <div>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",gap:12,flexWrap:"wrap"}}>
        <div>
          <SectionTitle>Emisores</SectionTitle>
          <SectionSub>Solo lectura por ahora — editar queda fuera de alcance hoy. Clic en una tarjeta para cambiar el emisor activo.</SectionSub>
        </div>
        <Btn type="button" variant="secondary" onClick={()=>setMostrandoFormulario(true)}>+ Agregar otro emisor</Btn>
      </div>
      <TwoCol>
        {emisores.map(e=>{
          const esActivo = e.rfc === emisorActivoRfc;
          return (
            <Card key={e.rfc} style={{cursor:"pointer",border:`1px solid ${esActivo?C.accent:C.border}`}} onClick={()=>setEmisorActivoRfc(e.rfc)}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10,gap:8}}>
                <div style={{minWidth:0}}>
                  <div style={{fontSize:14,fontWeight:600,color:C.text,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{e.razon_social}</div>
                  <div style={{fontSize:12,color:C.textMuted,fontFamily:"monospace",marginTop:2}}>{e.rfc}</div>
                </div>
                <div style={{display:"flex",flexDirection:"column",gap:4,alignItems:"flex-end",flexShrink:0}}>
                  {esActivo && <span style={{background:C.accentSoft,color:C.accentBorder,fontSize:11,fontWeight:600,padding:"3px 10px",borderRadius:20,whiteSpace:"nowrap"}}>✓ Seleccionado</span>}
                  <span style={{background:e.estado==="Activo"?C.accentSoft:C.dangerSoft,color:e.estado==="Activo"?C.accentBorder:C.danger,fontSize:11,fontWeight:600,padding:"3px 10px",borderRadius:20,whiteSpace:"nowrap"}}>{e.estado}</span>
                </div>
              </div>
              <div style={{fontSize:13,color:C.textSec,marginBottom:4}}>Régimen fiscal: <strong style={{color:C.text}}>{e.regimen_fiscal}</strong></div>
              <div style={{fontSize:13,color:C.textSec,marginBottom:4}}>CP expedición: <strong style={{color:C.text}}>{e.codigo_postal}</strong></div>
              <div style={{fontSize:13,color:C.textSec}}>Dado de alta por: <strong style={{color:C.text}}>{e.creado_por_rfc||"—"}</strong></div>
            </Card>
          );
        })}
      </TwoCol>
    </div>
  );
}

function Series(){
  const {series,loading,error} = useSeries();

  if (error) return <Placeholder title="Series y folios" detail={`No se pudo conectar con administracion (${ADMINISTRACION_BASE}): ${error}`}/>;
  if (loading) return <Placeholder title="Series y folios" detail="Cargando datos reales…"/>;
  if (series.length===0) return <Placeholder title="Series y folios" detail="Todavía no hay series en uso — se crean automáticamente al primer timbrado."/>;

  return (
    <div>
      <SectionTitle>Series y folios</SectionTitle>
      <SectionSub>Solo lectura — las series se crean automáticamente al primer timbrado, no hay alta manual todavía.</SectionSub>
      <Card>
        <table style={{width:"100%",borderCollapse:"collapse",fontSize:13}}>
          <thead>
            <tr style={{textAlign:"left",color:C.textMuted,fontSize:11,textTransform:"uppercase"}}>
              <th style={{padding:"6px 8px 10px 0"}}>Emisor</th>
              <th style={{padding:"6px 8px 10px 0"}}>Serie</th>
              <th style={{padding:"6px 8px 10px 0"}}>Último folio</th>
            </tr>
          </thead>
          <tbody>
            {series.map(s=>(
              <tr key={`${s.emisor_rfc}-${s.serie}`} style={{borderTop:`1px solid ${C.border}`}}>
                <td style={{padding:"8px 8px 8px 0",color:C.textSec,fontFamily:"monospace"}}>{s.emisor_rfc}</td>
                <td style={{padding:"8px 8px 8px 0",fontWeight:600,color:C.text}}>{s.serie}</td>
                <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{s.ultimo_folio}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function Usuarios(){
  const {usuarios,loading,error} = useUsuarios();

  if (error) return <Placeholder title="Usuarios" detail={`No se pudo conectar con auth (${AUTH_BASE}): ${error}`}/>;
  if (loading) return <Placeholder title="Usuarios" detail="Cargando datos reales…"/>;
  if (usuarios.length===0) return <Placeholder title="Usuarios" detail="Todavía no hay usuarios registrados."/>;

  return (
    <div>
      <SectionTitle>Usuarios</SectionTitle>
      <SectionSub>Solo lectura — promover a admin y editar/eliminar quedan fuera hasta resolver el diseño de roles (ver #10).</SectionSub>
      <Card>
        <table style={{width:"100%",borderCollapse:"collapse",fontSize:13}}>
          <thead>
            <tr style={{textAlign:"left",color:C.textMuted,fontSize:11,textTransform:"uppercase"}}>
              <th style={{padding:"6px 8px 10px 0"}}>Email</th>
              <th style={{padding:"6px 8px 10px 0"}}>RFC</th>
              <th style={{padding:"6px 8px 10px 0"}}>Nombre</th>
              <th style={{padding:"6px 8px 10px 0"}}>Usuario</th>
              <th style={{padding:"6px 8px 10px 0"}}>Rol</th>
              <th style={{padding:"6px 8px 10px 0"}}>Creado</th>
            </tr>
          </thead>
          <tbody>
            {usuarios.map(u=>(
              <tr key={u.id} style={{borderTop:`1px solid ${C.border}`}}>
                <td style={{padding:"8px 8px 8px 0",color:C.text}}>{u.email}</td>
                <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{u.rfc_personal}</td>
                <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{u.nombre||"—"}</td>
                <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{u.usuario||"—"}</td>
                <td style={{padding:"8px 8px 8px 0"}}>
                  <span style={{background:u.rol==="admin"?C.accentSoft:C.infoSoft,color:u.rol==="admin"?C.accentBorder:C.info,fontSize:11,fontWeight:600,padding:"3px 10px",borderRadius:20}}>{u.rol}</span>
                </td>
                <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{new Date(u.created_at).toLocaleDateString("es-MX")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: REPORTE
// ═══════════════════════════════════════════════════════════════════════════════
const MESES_CORTOS=["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];

function ReporteMensual(){
  const {facturas,loading,error} = useFacturas();
  const resumen = useResumenEjecutivo();

  if (error) return <Placeholder title="Reporte mensual" detail={`No se pudo conectar con facturacion (${FACTURACION_BASE}): ${error}`}/>;
  if (loading) return <Placeholder title="Reporte mensual" detail="Cargando datos reales…"/>;
  if (facturas.length===0) return <Placeholder title="Reporte mensual" detail="Todavía no hay facturas timbradas para reportar."/>;

  const porMes = {};
  for (const f of facturas) {
    const d = new Date(f.fecha_timbrado);
    const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}`;
    porMes[key] = (porMes[key]||0) + f.total;
  }
  const meses = Object.keys(porMes).sort();
  const vals = meses.map(k=>porMes[k]);
  const maxV = Math.max(...vals, 1);
  const totalAcumulado = facturas.reduce((s,f)=>s+f.total,0);
  const rangoLabel = meses.length>1
    ? `${MESES_CORTOS[Number(meses[0].slice(5))-1]} ${meses[0].slice(0,4)} – ${MESES_CORTOS[Number(meses[meses.length-1].slice(5))-1]} ${meses[meses.length-1].slice(0,4)}`
    : `${MESES_CORTOS[Number(meses[0].slice(5))-1]} ${meses[0].slice(0,4)}`;

  return (
    <div>
      <SectionTitle>Reporte mensual</SectionTitle>
      <Card style={{marginTop:12}}>
        <div style={{fontSize:11,color:C.textMuted,marginBottom:12,textTransform:"uppercase",letterSpacing:"0.06em"}}>Facturación real · {rangoLabel}</div>
        <div style={{display:"flex",alignItems:"flex-end",gap:8,height:130,padding:"0 4px"}}>
          {meses.map((k,i)=>(
            <div key={k} style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center",gap:4}}>
              <div style={{fontSize:9,color:C.textMuted,textAlign:"center"}}>{(vals[i]/1000).toFixed(1)}k</div>
              <div style={{width:"100%",background:i===meses.length-1?C.accent:C.primary,borderRadius:"5px 5px 0 0",height:`${(vals[i]/maxV)*100}px`,minHeight:2,opacity:i===meses.length-1?1:.7}}/>
              <div style={{fontSize:11,color:C.textSec,fontWeight:i===meses.length-1?700:400}}>{MESES_CORTOS[Number(k.slice(5))-1]}</div>
            </div>
          ))}
        </div>
        <div style={{borderTop:`1px solid ${C.border}`,marginTop:14,paddingTop:12,display:"flex",gap:20,flexWrap:"wrap"}}>
          {[["Total acumulado",fmt(totalAcumulado)],["CFDIs emitidos",String(facturas.length)],["Promedio",fmt(totalAcumulado/facturas.length)]].map(([l,v])=>(
            <div key={l}><div style={{fontSize:10,color:C.textMuted,marginBottom:3,textTransform:"uppercase"}}>{l}</div><div style={{fontSize:16,fontWeight:700,color:C.text}}>{v}</div></div>
          ))}
        </div>
        <Btn variant="secondary" style={{marginTop:12}} disabled={resumen.loading}
          onClick={()=>resumen.generar({
            periodo_inicio: `${meses[0]}-01`,
            periodo_fin: new Date().toISOString().slice(0,10),
            datos_facturacion: {
              total_acumulado: totalAcumulado,
              num_facturas: facturas.length,
              promedio: totalAcumulado/facturas.length,
              por_mes: porMes,
            },
            incluir_comparativo: meses.length>1,
          })}>
          {resumen.loading ? "Generando…" : "Generar resumen ejecutivo →"}
        </Btn>

        {resumen.error && (
          <div style={{marginTop:12,padding:"10px 12px",borderRadius:8,background:C.dangerSoft,color:C.danger,fontSize:12}}>
            ⚠ No se pudo generar el resumen: {resumen.error}. Revisa que ANTHROPIC_API_KEY esté configurada (ver #41).
          </div>
        )}

        {resumen.resultado && !resumen.resultado.texto_raw && (
          <div style={{marginTop:16,borderTop:`1px solid ${C.border}`,paddingTop:16}}>
            <div style={{fontSize:16,fontWeight:700,color:C.text,marginBottom:12}}>{resumen.resultado.titulo}</div>

            <KPIGrid>
              {(resumen.resultado.kpis_principales||[]).map((k,i)=>(
                <KPI key={i} label={k.nombre} value={k.valor}
                  sub={k.nota ? `${k.tendencia==="sube"?"↑":k.tendencia==="baja"?"↓":"→"} ${k.nota}` : undefined}/>
              ))}
            </KPIGrid>

            {resumen.resultado.texto_ejecutivo && (
              <p style={{fontSize:13,color:C.textSec,lineHeight:1.6,marginBottom:16}}>{resumen.resultado.texto_ejecutivo}</p>
            )}

            <TwoCol>
              {[["Hallazgos",resumen.resultado.hallazgos],["Riesgos",resumen.resultado.riesgos],["Recomendaciones",resumen.resultado.recomendaciones]].map(([titulo,items])=>(
                (items && items.length>0) && (
                  <Card key={titulo}>
                    <div style={{fontSize:11,color:C.textMuted,marginBottom:10,textTransform:"uppercase",letterSpacing:"0.06em"}}>{titulo}</div>
                    <ul style={{margin:0,paddingLeft:18,fontSize:13,color:C.textSec,lineHeight:1.7}}>
                      {items.map((it,i)=><li key={i}>{it}</li>)}
                    </ul>
                  </Card>
                )
              ))}
            </TwoCol>
          </div>
        )}
      </Card>
    </div>
  );
}

function DashboardCostos(){
  const { emisorActivoRfc } = useEmisores();
  const {datos,loading,error} = useCostosResumen(emisorActivoRfc);

  if (error) return <Placeholder title="Dashboard de costos" detail={`No se pudo conectar con facturacion (${FACTURACION_BASE}): ${error}`}/>;
  if (loading) return <Placeholder title="Dashboard de costos" detail="Cargando datos reales…"/>;

  const costoTotal = datos.reduce((s,d)=>s+d.costo_total,0);
  const timbresTotal = datos.reduce((s,d)=>s+d.num_timbres,0);
  const costoPromedio = timbresTotal>0 ? costoTotal/timbresTotal : 0;

  return (
    <div>
      <SectionTitle>Dashboard de costos</SectionTitle>
      <SectionSub>Costo real de Finkok por timbre (#6) · margen y costo de WhatsApp fuera de alcance por ahora (#7, #16)</SectionSub>

      <KPIGrid>
        <KPI label="Costo Finkok acumulado" value={fmt(costoTotal)} sub={`${timbresTotal} timbre${timbresTotal===1?"":"s"}`} dark/>
        <KPI label="Costo promedio por timbre" value={fmt(costoPromedio)}/>
        <KPI label="Costo WhatsApp por interacción" value="Pendiente" sub="Requiere #7 (en pausa)"/>
        <KPI label="Margen por negocio" value="Pendiente" sub="Requiere #7 + #16 (precios)"/>
      </KPIGrid>

      <Card>
        <div style={{fontSize:11,color:C.textMuted,marginBottom:12,textTransform:"uppercase",letterSpacing:"0.06em"}}>Desglose por mes y emisor</div>
        {datos.length===0 ? (
          <div style={{color:C.textMuted,fontSize:13,padding:"12px 0"}}>Todavía no hay timbres con costo registrado (#6 solo aplica a timbrados posteriores a su implementación).</div>
        ) : (
          <table style={{width:"100%",borderCollapse:"collapse",fontSize:13}}>
            <thead>
              <tr style={{textAlign:"left",color:C.textMuted,fontSize:11,textTransform:"uppercase"}}>
                <th style={{padding:"6px 8px 10px 0"}}>Periodo</th>
                <th style={{padding:"6px 8px 10px 0"}}>Emisor</th>
                <th style={{padding:"6px 8px 10px 0"}}>Timbres</th>
                <th style={{padding:"6px 8px 10px 0"}}>Costo total</th>
                <th style={{padding:"6px 8px 10px 0"}}>Costo promedio</th>
              </tr>
            </thead>
            <tbody>
              {datos.map((d,i)=>(
                <tr key={`${d.periodo}-${d.emisor_rfc}`} style={{borderTop:`1px solid ${C.border}`}}>
                  <td style={{padding:"8px 8px 8px 0",fontWeight:600,color:C.text}}>{d.periodo}</td>
                  <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{d.emisor_rfc}</td>
                  <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{d.num_timbres}</td>
                  <td style={{padding:"8px 8px 8px 0",color:C.text}}>{fmt(d.costo_total)}</td>
                  <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{fmt(d.costo_promedio)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div style={{marginTop:14,padding:"10px 12px",borderRadius:8,background:C.warnSoft,color:C.warn,fontSize:12}}>
          ⏳ Pendiente: costo de conversación de WhatsApp (#7, en pausa) y cálculo de margen por negocio (#16, precios diferidos) — se agregarán a este dashboard cuando esas tarjetas se resuelvan. No se muestran como $0 para no dar una cifra falsa.
        </div>
      </Card>
    </div>
  );
}

function ContadorVirtual(){
  const {emisores,loading:loadingEmisores,error:errorEmisores,emisorActivoRfc} = useEmisores();
  const emisor = emisores.find(e=>e.rfc===emisorActivoRfc);
  const hoy = new Date();
  const [periodo,setPeriodo] = useState(`${hoy.getFullYear()}-${String(hoy.getMonth()+1).padStart(2,"0")}`);
  const [anio,mes] = periodo.split("-").map(Number);
  const {datos,loading,error} = useContadorVirtualISRResico(emisor?.rfc, anio, mes);

  if (errorEmisores) return <Placeholder title="Contador virtual" detail={`No se pudo conectar con administracion (${ADMINISTRACION_BASE}): ${errorEmisores}`}/>;
  if (loadingEmisores) return <Placeholder title="Contador virtual" detail="Cargando datos reales…"/>;
  if (!emisor) return <Placeholder title="Contador virtual" detail="Todavía no hay un emisor registrado."/>;

  return (
    <div>
      <SectionTitle>Contador virtual — ISR provisional (RESICO PF)</SectionTitle>
      <SectionSub>Fase 1 de #40: solo RESICO Personas Físicas, solo ingresos ya facturados con pago en una sola exhibición (PUE).</SectionSub>

      <Card style={{marginBottom:12}}>
        <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:6}}>Periodo</label>
        <input type="month" value={periodo} onChange={e=>setPeriodo(e.target.value)}
          style={{border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff"}}/>
      </Card>

      {loading && <Placeholder title="Contador virtual" detail="Calculando…"/>}
      {!loading && error && <Placeholder title="Contador virtual" detail={`No se pudo conectar con facturacion (${FACTURACION_BASE}): ${error}`}/>}

      {!loading && !error && datos && !datos.aplica && (
        <Card>
          <div style={{fontSize:14,fontWeight:600,color:C.text,marginBottom:6}}>No aplica para tu régimen fiscal</div>
          <div style={{fontSize:13,color:C.textSec}}>{datos.motivo_no_aplica}</div>
        </Card>
      )}

      {!loading && !error && datos && datos.aplica && (
        <>
          <KPIGrid>
            <KPI label="Ingreso PUE del periodo" value={fmt(datos.ingreso_pue_incluido)} sub={`${datos.facturas_pue_incluidas.length} factura${datos.facturas_pue_incluidas.length===1?"":"s"}`} dark/>
            <KPI label="Tasa aplicada" value={`${(datos.tasa_aplicada*100).toFixed(2)}%`}/>
            <KPI label="ISR provisional estimado" value={fmt(datos.isr_estimado)}/>
          </KPIGrid>

          {datos.excede_tope_mensual && (
            <div style={{marginBottom:12,padding:"10px 12px",borderRadius:8,background:C.dangerSoft,color:C.danger,fontSize:12}}>
              ⚠ El ingreso del mes excede el tope mensual normal de RESICO (~$291,666.67, equivalente al tope anual de $3.5M) — se aplicó la tasa más alta como referencia, pero esto puede indicar que ya no calificas para este régimen.
            </div>
          )}

          <Card style={{marginBottom:12}}>
            <div style={{fontSize:11,color:C.textMuted,marginBottom:12,textTransform:"uppercase",letterSpacing:"0.06em"}}>CFDI PUE incluidos en el cálculo</div>
            {datos.facturas_pue_incluidas.length===0 ? (
              <div style={{color:C.textMuted,fontSize:13}}>Sin CFDI PUE en este periodo.</div>
            ) : (
              <table style={{width:"100%",borderCollapse:"collapse",fontSize:13}}>
                <tbody>
                  {datos.facturas_pue_incluidas.map(f=>(
                    <tr key={f.uuid} style={{borderTop:`1px solid ${C.border}`}}>
                      <td style={{padding:"6px 8px 6px 0",fontFamily:"monospace",fontWeight:600,color:C.primary}}>{f.folio}</td>
                      <td style={{padding:"6px 8px 6px 0",color:C.textSec}}>{f.receptor_rfc}</td>
                      <td style={{padding:"6px 8px 6px 0",textAlign:"right",color:C.text}}>{fmt(f.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card style={{marginBottom:12}}>
            <div style={{fontSize:11,color:C.textMuted,marginBottom:12,textTransform:"uppercase",letterSpacing:"0.06em"}}>CFDI PPD excluidos del cálculo</div>
            {datos.facturas_ppd_excluidas.length===0 ? (
              <div style={{color:C.textMuted,fontSize:13}}>Sin CFDI PPD en este periodo.</div>
            ) : (
              <>
                <table style={{width:"100%",borderCollapse:"collapse",fontSize:13,marginBottom:10}}>
                  <tbody>
                    {datos.facturas_ppd_excluidas.map(f=>(
                      <tr key={f.uuid} style={{borderTop:`1px solid ${C.border}`}}>
                        <td style={{padding:"6px 8px 6px 0",fontFamily:"monospace",fontWeight:600,color:C.textSec}}>{f.folio}</td>
                        <td style={{padding:"6px 8px 6px 0",color:C.textSec}}>{f.receptor_rfc}</td>
                        <td style={{padding:"6px 8px 6px 0",textAlign:"right",color:C.textSec}}>{fmt(f.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{fontSize:12,color:C.textMuted}}>
                  Excluidos del cálculo — requieren complemento de pago para saber cuándo se cobraron realmente.
                </div>
              </>
            )}
          </Card>
        </>
      )}

      {!loading && !error && datos && (
        <div style={{marginTop:4,padding:"12px 14px",borderRadius:8,background:C.warnSoft,color:C.warn,fontSize:13,fontWeight:600}}>
          ⚠ {datos.disclaimer}
        </div>
      )}
    </div>
  );
}

function Placeholder({title,detail}){
  return (
    <div style={{display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",height:260,color:C.textMuted,padding:"0 16px",textAlign:"center"}}>
      <div style={{fontSize:36,marginBottom:12}}>🚧</div>
      <div style={{fontSize:15,fontWeight:600,color:C.textSec}}>{title}</div>
      <div style={{fontSize:12,marginTop:5}}>{detail || "Conecta el microservicio para habilitar esta vista"}</div>
    </div>
  );
}

const VIEWS={
  nueva:<NuevaFactura/>,generadas:<FacturasGeneradas/>,recibidas:<Placeholder title="Facturas recibidas"/>,
  reporte:<ReporteMensual/>,costos:<DashboardCostos/>,contador:<ContadorVirtual/>,lector:<LectorDocumentos/>,chat:<ChatFiscal/>,
  anomalias:<Anomalias/>,conciliacion:<Placeholder title="Conciliación bancaria"/>,
  emisores:<Emisores/>,clientes:<Clientes/>,
  usuarios:<Usuarios/>,series:<Series/>,
  addenda:<Placeholder title="Addenda AES"/>,
};

// ═══════════════════════════════════════════════════════════════════════════════
// SIDEBAR CONTENT (compartido entre drawer y sidebar fijo)
// ═══════════════════════════════════════════════════════════════════════════════
function SidebarNav({active, navigate, expanded, toggle, compact=false}){
  return (
    <>
      <div style={{padding:compact?"14px 0 12px":"20px 18px 14px",borderBottom:"1px solid rgba(255,255,255,.08)",textAlign:compact?"center":"left"}}>
        {compact
          ? <img src={logoAcierto} alt="Acierto" style={{width:28,height:28,borderRadius:6,display:"inline-block"}}/>
          : <>
              <img src={logoAcierto} alt="Acierto" style={{width:110,maxWidth:"100%",borderRadius:6,display:"block"}}/>
              <div style={{fontSize:13,fontWeight:600,color:"rgba(255,255,255,.9)",marginTop:6}}>Portal Inteligente</div>
            </>
        }
      </div>
      <nav style={{flex:1,padding:"8px 0",overflowY:"auto"}}>
        {NAV.map(item=>(
          <div key={item.id}>
            <div onClick={()=>{if(item.children.length)toggle(item.id);else navigate(item.id);}}
              style={{display:"flex",alignItems:"center",gap:compact?0:9,padding:compact?"10px 0":"9px 18px",justifyContent:compact?"center":"flex-start",cursor:"pointer",color:"rgba(255,255,255,.7)",fontSize:13,fontWeight:600,userSelect:"none"}}>
              <span style={{fontSize:compact?18:15}}>{item.icon}</span>
              {!compact&&<span style={{flex:1}}>{item.label}</span>}
              {!compact&&item.id==="ia"&&<span style={{fontSize:9,padding:"2px 6px",borderRadius:8,background:"rgba(0,200,150,.2)",color:C.accent}}>IA</span>}
              {!compact&&item.children.length>0&&<span style={{fontSize:10,opacity:.5}}>{expanded[item.id]?"▾":"▸"}</span>}
            </div>
            {!compact&&item.id==="addenda"&&(
              <div onClick={()=>navigate("addenda")}
                style={{padding:"6px 18px 6px 38px",cursor:"pointer",fontSize:13,color:active==="addenda"?C.accent:"rgba(255,255,255,.55)",background:active==="addenda"?"rgba(0,200,150,.1)":"transparent",borderLeft:active==="addenda"?`2px solid ${C.accent}`:"2px solid transparent"}}>
                Addenda AES
              </div>
            )}
            {!compact&&expanded[item.id]&&item.children.map(child=>(
              <div key={child} onClick={()=>navigate(child)}
                style={{padding:"6px 18px 6px 38px",cursor:"pointer",fontSize:13,color:active===child?C.accent:"rgba(255,255,255,.55)",background:active===child?"rgba(0,200,150,.1)":"transparent",borderLeft:active===child?`2px solid ${C.accent}`:"2px solid transparent",transition:"all .15s"}}>
                {LABELS[child]}
              </div>
            ))}
          </div>
        ))}
      </nav>
      {!compact&&(
        <div style={{padding:"12px 18px",borderTop:"1px solid rgba(255,255,255,.08)"}}>
          <div style={{fontSize:10,color:"rgba(255,255,255,.3)"}}>v2.0 · 6 microservicios</div>
          <div style={{display:"flex",gap:4,marginTop:5,flexWrap:"wrap"}}>
            {["Facturación","Admin","IA","Auth"].map(s=>(
              <span key={s} style={{fontSize:9,padding:"2px 6px",borderRadius:6,background:"rgba(0,200,150,.15)",color:C.accent}}>{s}</span>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// APP SHELL
// ═══════════════════════════════════════════════════════════════════════════════
function AppShell({onLogout}){
  const {isMobile,isTablet}=useBreakpoint();
  const [active,setActive]=useState("generadas");
  const [expanded,setExpanded]=useState({facturas:true,ia:true,admin:false});
  const [drawerOpen,setDrawerOpen]=useState(false);
  const toggle=id=>setExpanded(e=>({...e,[id]:!e[id]}));
  const navigate=id=>{setActive(id);setDrawerOpen(false);};

  // Header conectado al Emisor real del Negocio del usuario logueado (#15) -
  // antes mostraba el mock EMISOR fijo ("Distribuidora Nacional SA de CV")
  // sin importar quien iniciara sesion. useEmisores() ya llega filtrado por
  // negocio_id (ver aislamiento de lecturas, #15), asi que el primero de la
  // lista es "el" emisor de esta cuenta - mismo criterio que ya usaba NuevaFactura.
  const {emisores,loading:cargandoEmisor,emisorActivoRfc,setEmisorActivoRfc}=useEmisores();
  // find() en vez de emisores[0] directo - con 1 solo emisor (caso de hoy)
  // emisorActivoRfc ya fue auto-seleccionado a ese mismo rfc en
  // EmisoresProvider, asi que esto resuelve exactamente igual que antes.
  // Con 2+ emisores, sigue al selector de abajo.
  const emisorActual=emisores.find(e=>e.rfc===emisorActivoRfc)??emisores[0];
  const nombreEmisor=cargandoEmisor?"Cargando…":(emisorActual?.razon_social||"Sin emisor registrado");
  const inicialesEmisor=emisorActual?.razon_social
    ? emisorActual.razon_social.split(" ").filter(Boolean).slice(0,2).map(w=>w[0].toUpperCase()).join("")
    : "—";

  const sidebarW = isMobile ? 0 : isTablet ? 52 : 232;

  return (
    <div style={{display:"flex",height:"100dvh",fontFamily:"'Inter',system-ui,sans-serif",background:C.surface,color:C.text,overflow:"hidden"}}>

      {/* Mobile drawer */}
      {isMobile&&drawerOpen&&(
        <div style={{position:"fixed",inset:0,zIndex:100,display:"flex"}}>
          <div style={{position:"absolute",inset:0,background:"rgba(0,0,0,.5)"}} onClick={()=>setDrawerOpen(false)}/>
          <aside style={{width:240,background:C.primary,display:"flex",flexDirection:"column",position:"relative",zIndex:1,flexShrink:0}}>
            <SidebarNav active={active} navigate={navigate} expanded={expanded} toggle={toggle} compact={false}/>
          </aside>
        </div>
      )}

      {/* Desktop/tablet sidebar */}
      {!isMobile&&(
        <aside style={{width:sidebarW,background:C.primary,display:"flex",flexDirection:"column",flexShrink:0,transition:"width .2s"}}>
          <SidebarNav active={active} navigate={navigate} expanded={expanded} toggle={toggle} compact={isTablet}/>
        </aside>
      )}

      <main style={{flex:1,display:"flex",flexDirection:"column",overflow:"hidden",minWidth:0}}>
        {/* Topbar */}
        <header style={{background:C.card,borderBottom:`1px solid ${C.border}`,padding:isMobile?"10px 14px":"12px 24px",display:"flex",alignItems:"center",justifyContent:"space-between",flexShrink:0,gap:8}}>
          <div style={{display:"flex",alignItems:"center",gap:10,minWidth:0}}>
            {isMobile&&(
              <button onClick={()=>setDrawerOpen(true)} aria-label="Abrir menú"
                style={{background:"transparent",border:"none",cursor:"pointer",fontSize:20,color:C.text,padding:0,lineHeight:1,flexShrink:0}}>☰</button>
            )}
            <div style={{minWidth:0}}>
              <div style={{fontSize:10,color:C.textMuted}}>Bienvenido de vuelta</div>
              <div style={{fontSize:isMobile?13:14,fontWeight:600,color:C.text,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{nombreEmisor}</div>
            </div>
          </div>
          <div style={{display:"flex",gap:10,alignItems:"center",flexShrink:0}}>
            {!isMobile&&(emisores.length>1
              ? (
                <select value={emisorActivoRfc||""} onChange={e=>setEmisorActivoRfc(e.target.value)}
                  style={{fontSize:11,color:C.textMuted,background:"transparent",border:`1px solid ${C.border}`,borderRadius:6,padding:"3px 6px",maxWidth:220,cursor:"pointer"}}>
                  {emisores.map(e=>(<option key={e.rfc} value={e.rfc}>{e.razon_social} — {e.rfc}</option>))}
                </select>
              )
              : <div style={{fontSize:11,color:C.textMuted,whiteSpace:"nowrap"}}>RFC: {cargandoEmisor?"…":(emisorActual?.rfc||"—")}</div>
            )}
            <div style={{position:"relative"}}>
              <div style={{width:7,height:7,borderRadius:"50%",background:C.danger,position:"absolute",top:-1,right:-1,border:"2px solid #fff"}}/>
              <span style={{fontSize:17,cursor:"pointer"}}>🔔</span>
            </div>
            <div style={{width:30,height:30,borderRadius:"50%",background:C.primary,display:"flex",alignItems:"center",justifyContent:"center",color:C.accent,fontWeight:700,fontSize:11,flexShrink:0}}>{inicialesEmisor}</div>
            <button onClick={onLogout} title="Cerrar sesión"
              style={{background:"transparent",border:`1px solid ${C.border}`,borderRadius:8,padding:"6px 10px",fontSize:12,color:C.textSec,cursor:"pointer",flexShrink:0}}>Salir</button>
          </div>
        </header>

        {/* Mobile bottom nav */}
        {isMobile&&(
          <div style={{display:"flex",background:C.primary,borderTop:"1px solid rgba(255,255,255,.1)",flexShrink:0,order:1}}>
            {[["generadas","📄","Facturas"],["lector","📥","Lector IA"],["chat","🤖","Chat IA"],["clientes","👥","Clientes"]].map(([id,ic,lbl])=>(
              <button key={id} onClick={()=>navigate(id)}
                style={{flex:1,background:"transparent",border:"none",cursor:"pointer",padding:"7px 2px",display:"flex",flexDirection:"column",alignItems:"center",gap:2}}>
                <span style={{fontSize:17}}>{ic}</span>
                <span style={{fontSize:9,color:active===id?C.accent:"rgba(255,255,255,.45)",fontWeight:active===id?700:400}}>{lbl}</span>
              </button>
            ))}
          </div>
        )}

        {/* Content area */}
        <div style={{flex:1,overflowY:"auto",padding:isMobile?"14px 12px":"22px 26px",WebkitOverflowScrolling:"touch",order:0}}>
          {VIEWS[active]||<Placeholder title={LABELS[active]}/>}
        </div>
      </main>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// ROOT — wrap con ToastProvider
// ═══════════════════════════════════════════════════════════════════════════════
function AuthGate(){
  const auth = useAuth();
  // Si la URL trae ?token=... (link del correo de recuperacion, ver
  // email_sender.py), arranca directo en "reset" sin pasar por "login" -
  // window.location.search se lee UNA vez al montar (useState con
  // funcion inicializadora), no en cada render. Sin react-router en el
  // proyecto: esto es deliberadamente el unico lugar que lee la URL.
  const [vista, setVista] = useState(() => (
    new URLSearchParams(window.location.search).get("token") ? "reset" : "login"
  )); // "login" | "registro" | "olvide" | "reset"
  const tokenReset = new URLSearchParams(window.location.search).get("token");
  if (!auth.isAuthenticated) {
    if (vista === "registro") return <CrearCuenta onRegistro={auth.registro} onIrALogin={()=>setVista("login")}/>;
    if (vista === "olvide") return <OlvideContrasena onSolicitar={auth.solicitarReset} onIrALogin={()=>setVista("login")}/>;
    if (vista === "reset") return <ResetPassword token={tokenReset} onConfirmar={auth.confirmarReset} onIrALogin={()=>setVista("login")}/>;
    return <Login onLogin={auth.login} onIrARegistro={()=>setVista("registro")} onIrAOlvide={()=>setVista("olvide")}/>;
  }
  // AuthGate nunca se desmonta entre login/logout (solo cambia que rama
  // renderiza), asi que "vista" sobrevive el logout tal cual quedo antes
  // de autenticarse - si el usuario paso por "Crear cuenta" antes de
  // loguearse, el logout regresaba ahi en vez de a "Iniciar sesion". Se
  // resetea aqui, no dentro de auth.logout() (useAuth no tiene ni debe
  // tener conocimiento del concepto de "vista", que es puramente de
  // AuthGate).
  const onLogout = () => { auth.logout(); setVista("login"); };
  return <EmisoresProvider><AppShell onLogout={onLogout}/></EmisoresProvider>;
}

export default function App(){
  return (
    <ToastProvider>
      <AuthGate/>
    </ToastProvider>
  );
}
