// Iconos de linea simple para las cards de planes. SVG a mano, sin
// dependencia externa (el proyecto solo usa react/react-dom).
export function IconEmprendedor({size=32,color="#2B6CB0"}) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 2C9.5 4.2 8 7.6 8 11c0 2.4.6 4.1 1.3 5.6L12 20l2.7-3.4C15.4 15.1 16 13.4 16 11c0-3.4-1.5-6.8-4-9z" />
      <circle cx="12" cy="10" r="1.5" />
      <path d="M8.5 16.5L6 19M15.5 16.5L18 19M12 20v2.5" />
    </svg>
  );
}

export function IconBasico({size=32,color="#2B6CB0"}) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 9l1.5-5h15L21 9" />
      <path d="M3 9v11h18V9" />
      <path d="M3 9c0 1.7 1.3 3 3 3s3-1.3 3-3c0 1.7 1.3 3 3 3s3-1.3 3-3c0 1.7 1.3 3 3 3s3-1.3 3-3" />
      <path d="M9 20v-6h6v6" />
    </svg>
  );
}

export function IconContador({size=32,color="#2B6CB0"}) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="8" cy="8" r="3.2" />
      <circle cx="17" cy="9" r="2.6" />
      <path d="M2.5 20c0-3.6 2.5-6 5.5-6s5.5 2.4 5.5 6" />
      <path d="M14 20c0-2.8 1.7-4.6 3.5-4.6s3.5 1.8 3.5 4.6" />
    </svg>
  );
}

export function IconDespacho({size=32,color="#2B6CB0"}) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 21h18" />
      <path d="M5 21V8l7-5 7 5v13" />
      <path d="M10 21v-6h4v6" />
      <path d="M9 10h.01M12 10h.01M15 10h.01M9 14h.01M15 14h.01" />
    </svg>
  );
}
