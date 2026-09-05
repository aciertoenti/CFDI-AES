// ─── App.jsx ── CFDI-AES · Responsive + Toast + Table fix ─────────────────────
import { useEffect, useState } from "react";
import useAuth from "./shared/hooks/useAuth";
import { EmisoresProvider } from "./shared/hooks/useEmisores";
import { ToastProvider } from "./shared/layout/ToastProvider";
import AppShell, { Placeholder } from "./shared/layout/AppShell";
import { NavProvider } from "./shared/layout/nav";
import Login from "./domains/auth/Login";
import OlvideContrasena from "./domains/auth/OlvideContrasena";
import ResetPassword from "./domains/auth/ResetPassword";
import CrearCuenta from "./domains/auth/CrearCuenta";
import PlanesLanding from "./domains/billing/PlanesLanding";
import Clientes from "./domains/administracion/Clientes";
import Emisores from "./domains/administracion/Emisores";
import Series from "./domains/administracion/Series";
import Usuarios from "./domains/administracion/Usuarios";
import NuevaFactura from "./domains/facturacion/NuevaFactura";
import NuevoTicket from "./domains/facturacion/NuevoTicket";
import FacturasGeneradas from "./domains/facturacion/FacturasGeneradas";
import ReporteMensual from "./domains/facturacion/ReporteMensual";
import DashboardCostos from "./domains/facturacion/DashboardCostos";
import ContadorVirtual from "./domains/facturacion/ContadorVirtual";
import LectorDocumentos from "./domains/ia/LectorDocumentos";
import ChatFiscal from "./domains/ia/ChatFiscal";
import Anomalias from "./domains/ia/Anomalias";

// ═══════════════════════════════════════════════════════════════════════════════
// NAVEGACIÓN
// ═══════════════════════════════════════════════════════════════════════════════
const NAV = [
  {id:"facturas",label:"Mis Facturas",icon:"📄",children:["nueva","ticket","generadas","recibidas","reporte","costos"]},
  {id:"ia",label:"IA",icon:"🤖",children:["contador","chat","lector","anomalias","conciliacion"]},
  {id:"admin",label:"Administración",icon:"⚙️",children:["emisores","clientes","usuarios","series"]},
];
const LABELS = {
  nueva:"Nueva Factura",ticket:"Nueva Venta (Ticket)",generadas:"Generadas",recibidas:"Recibidas",reporte:"Reporte Mensual",costos:"Dashboard de Costos",contador:"Cálculo de Impuestos",
  lector:"Lector de Documentos",chat:"Asistente de IA",anomalias:"Anomalías IA",conciliacion:"Conciliación",
  emisores:"Emisores",clientes:"Clientes",usuarios:"Usuarios",series:"Series",
};
const VIEWS={
  nueva:<NuevaFactura/>,ticket:<NuevoTicket/>,generadas:<FacturasGeneradas/>,recibidas:<Placeholder title="Facturas recibidas"/>,
  reporte:<ReporteMensual/>,costos:<DashboardCostos/>,contador:<ContadorVirtual/>,lector:<LectorDocumentos/>,chat:<ChatFiscal/>,
  anomalias:<Anomalias/>,conciliacion:<Placeholder title="Conciliación bancaria"/>,
  emisores:<Emisores/>,clientes:<Clientes/>,
  usuarios:<Usuarios/>,series:<Series/>,
};

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
  const [vista, setVista] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("vista") || (params.get("token") ? "reset" : "landing");
  }); // "landing" | "login" | "registro" | "prueba" | "olvide" | "reset"
  // Plan elegido en la landing (?plan=emprendedor) - se lee de la URL igual
  // que "vista", para que sobreviva un refresh a mitad del registro. Sin
  // esto, el plan se perdia entre PlanesLanding y CrearCuenta: quedaba en
  // la URL pero nunca llegaba al POST /auth/registro, y toda cuenta nueva
  // caia en el default "basico" del backend sin importar el plan elegido
  // (hallazgo real, confirmado en BD - 24 ago 2026, verificacion E2E).
  const [planSeleccionado, setPlanSeleccionado] = useState(() => new URLSearchParams(window.location.search).get("plan"));
  const tokenReset = new URLSearchParams(window.location.search).get("token");
  useEffect(() => {
    const onPopState = () => {
      const params = new URLSearchParams(window.location.search);
      setVista(params.get("vista") || (params.get("token") ? "reset" : "landing"));
      setPlanSeleccionado(params.get("plan"));
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  const navigatePublic = (nextVista, plan, periodicidad) => {
    const params = new URLSearchParams();
    params.set("vista", nextVista);
    if (plan) params.set("plan", plan);
    if (periodicidad) params.set("periodicidad", periodicidad);
    window.history.pushState({}, "", `${window.location.pathname}?${params.toString()}`);
    setVista(nextVista);
    setPlanSeleccionado(plan || null);
  };
  if (!auth.isAuthenticated) {
    if (vista === "landing") return <PlanesLanding onIrALogin={()=>navigatePublic("login")} onIrARegistro={()=>navigatePublic("registro")} onElegirPlan={(plan,periodicidad)=>navigatePublic("registro", plan, periodicidad)}/>
    if (vista === "registro") return <CrearCuenta plan={planSeleccionado} onRegistro={auth.registro} onIrALogin={()=>navigatePublic("login")} onIrAHome={()=>navigatePublic("landing")}/>;
    if (vista === "prueba") return <CrearCuenta subtitulo="Prueba Controlada" plan={planSeleccionado} onRegistro={auth.registro} onIrALogin={()=>navigatePublic("login")} onIrAHome={()=>navigatePublic("landing")}/>;
    if (vista === "olvide") return <OlvideContrasena onSolicitar={auth.solicitarReset} onIrALogin={()=>setVista("login")}/>;
    if (vista === "reset") return <ResetPassword token={tokenReset} onConfirmar={auth.confirmarReset} onIrALogin={()=>setVista("login")}/>;
    return <Login onLogin={auth.login} onIrARegistro={()=>navigatePublic("registro")} onIrAOlvide={()=>setVista("olvide")} onIrAHome={()=>navigatePublic("landing")}/>;
  }
  // AuthGate nunca se desmonta entre login/logout (solo cambia que rama
  // renderiza), asi que "vista" sobrevive el logout tal cual quedo antes
  // de autenticarse - si el usuario paso por "Crear cuenta" antes de
  // loguearse, el logout regresaba ahi en vez de a "Iniciar sesion". Se
  // resetea aqui, no dentro de auth.logout() (useAuth no tiene ni debe
  // tener conocimiento del concepto de "vista", que es puramente de
  // AuthGate).
  const onLogout = () => { auth.logout(); window.history.pushState({}, "", `${window.location.pathname}?vista=landing`); setVista("landing"); };
  return <EmisoresProvider><NavProvider><AppShell onLogout={onLogout} usuarioActual={auth.usuarioActual} views={VIEWS} labels={LABELS} nav={NAV}/></NavProvider></EmisoresProvider>;
}

export default function App(){
  return (
    <ToastProvider>
      <AuthGate/>
    </ToastProvider>
  );
}
