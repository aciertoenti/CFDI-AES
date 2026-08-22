import { useEffect, useState } from "react";

export default function useBreakpoint() {
  const [w, setW] = useState(typeof window !== "undefined" ? window.innerWidth : 1200);
  useEffect(() => {
    const h = () => setW(window.innerWidth);
    window.addEventListener("resize", h);
    return () => window.removeEventListener("resize", h);
  }, []);
  return { w, isMobile: w < 768, isTablet: w >= 768 && w < 1024, isDesktop: w >= 1024 };
}
