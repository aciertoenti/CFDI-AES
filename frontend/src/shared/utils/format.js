export const C = {
  primary:"#0A2540", accent:"#00C896", accentSoft:"#E6FAF5", accentBorder:"#00A87E",
  surface:"#F7F9FC", card:"#FFFFFF", border:"#E4E9F0",
  text:"#0A2540", textSec:"#5A6B7E", textMuted:"#8A9BB0",
  danger:"#E53E3E", dangerSoft:"#FFF5F5", warn:"#DD6B20", warnSoft:"#FFFAF0",
  info:"#2B6CB0", infoSoft:"#EBF8FF",
};

export const fmt = n => new Intl.NumberFormat("es-MX",{style:"currency",currency:"MXN"}).format(n);

export const detalleError = (data, res) => Array.isArray(data.detail)
  ? data.detail.map(d => d.msg || JSON.stringify(d)).join(", ")
  : (data.detail || `HTTP ${res.status}`);
