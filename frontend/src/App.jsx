// ─── App.jsx ── CFDI-AES · Responsive + Toast + Table fix ─────────────────────
import { useState } from "react";
import useAuth from "./shared/hooks/useAuth";
import { EmisoresProvider } from "./shared/hooks/useEmisores";
import { ToastProvider } from "./shared/layout/ToastProvider";
import AppShell, { Placeholder } from "./shared/layout/AppShell";
import Login from "./domains/auth/Login";
import OlvideContrasena from "./domains/auth/OlvideContrasena";
import ResetPassword from "./domains/auth/ResetPassword";
import CrearCuenta from "./domains/auth/CrearCuenta";
import Clientes from "./domains/administracion/Clientes";
import Emisores from "./domains/administracion/Emisores";
import Series from "./domains/administracion/Series";
import Usuarios from "./domains/administracion/Usuarios";
import NuevaFactura from "./domains/facturacion/NuevaFactura";
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
const VIEWS={
  nueva:<NuevaFactura/>,generadas:<FacturasGeneradas/>,recibidas:<Placeholder title="Facturas recibidas"/>,
  reporte:<ReporteMensual/>,costos:<DashboardCostos/>,contador:<ContadorVirtual/>,lector:<LectorDocumentos/>,chat:<ChatFiscal/>,
  anomalias:<Anomalias/>,conciliacion:<Placeholder title="Conciliación bancaria"/>,
  emisores:<Emisores/>,clientes:<Clientes/>,
  usuarios:<Usuarios/>,series:<Series/>,
  addenda:<Placeholder title="Addenda AES"/>,
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
  return <EmisoresProvider><AppShell onLogout={onLogout} usuarioActual={auth.usuarioActual} views={VIEWS} labels={LABELS} nav={NAV}/></EmisoresProvider>;
}

export default function App(){
  return (
    <ToastProvider>
      <AuthGate/>
    </ToastProvider>
  );
}
