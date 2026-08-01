/**
 * Componente reutilizable de KPI para el Dashboard.
 * Extraído de App.jsx para facilitar reutilización y tests.
 */

const C = {
  primary: "#0A2540",
  accent: "#00C896",
  card: "#FFFFFF",
  border: "#E4E9F0",
  text: "#0A2540",
  textMuted: "#8A9BB0",
};

/**
 * @param {object} props
 * @param {string} props.label   - Etiqueta superior
 * @param {string|number} props.value  - Valor principal
 * @param {string} [props.sub]   - Texto secundario opcional
 * @param {boolean} [props.dark] - Variante oscura (fondo primary)
 */
export default function KPICard({ label, value, sub, dark }) {
  return (
    <div
      style={{
        background: dark ? C.primary : C.card,
        border: `1px solid ${dark ? "transparent" : C.border}`,
        borderRadius: 12,
        padding: "14px",
        minWidth: 0,
        boxSizing: "border-box",
      }}
    >
      <div
        style={{
          fontSize: 10,
          color: dark ? "rgba(255,255,255,.5)" : C.textMuted,
          marginBottom: 5,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          color: dark ? C.accent : C.text,
          lineHeight: 1,
        }}
      >
        {value}
      </div>
      {sub && (
        <div
          style={{
            fontSize: 11,
            color: dark ? "rgba(255,255,255,.4)" : C.textMuted,
            marginTop: 3,
          }}
        >
          {sub}
        </div>
      )}
    </div>
  );
}
