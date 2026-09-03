import { createContext, useContext, useState } from "react";

// Navegacion in-app (sin react-router, ver App.jsx). AppShell renderiza
// views[active]; este contexto sube ese `active` y agrega un `payload`
// opcional para pasarle datos a la vista destino al navegar - hoy lo usa
// "Abrir" en la lista de Borradores para entregarle el borrador a
// NuevaFactura, que no puede recibir props (views es un objeto estatico
// de elementos JSX).
const NavCtx = createContext(null);

export function NavProvider({ children, initial = "nueva" }) {
  const [active, setActive] = useState(initial);
  const [payload, setPayload] = useState(null);
  // navigate(id) navega y limpia cualquier payload viejo; navigate(id, data)
  // navega entregando `data` a la vista destino (que la consume una vez).
  const navigate = (id, data = null) => {
    setActive(id);
    setPayload(data);
  };
  return (
    <NavCtx.Provider value={{ active, navigate, payload, setPayload }}>
      {children}
    </NavCtx.Provider>
  );
}

export function useNav() {
  return useContext(NavCtx);
}
