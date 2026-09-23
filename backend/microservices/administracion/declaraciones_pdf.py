"""
Lectura y clasificacion del CONTENIDO (capa de texto) de PDFs de
declaraciones anuales - reporte 189. Resuelve el gap real encontrado en
pruebas: antes se guardaba el ejercicio/tipo que el usuario elegia a
mano, sin verificar contra el documento (una prueba real guardo un
acuse de 2013 como si fuera 2025, y una opinion de cumplimiento como si
fuera una declaracion).

Alcance: SOLO capa de texto (pypdf), NUNCA OCR/imagenes - un PDF
escaneado sin capa de texto cae en NO_RECONOCIDO, no se intenta leer
la imagen.

Seguridad/robustez: cualquier error de lectura (PDF corrupto, mas de
MAX_PAGINAS, timeout) se captura y traduce a "no se pudo leer el
documento" - NUNCA una excepcion sin manejar que provoque un 500 en el
endpoint que use este modulo.
"""
import io
import multiprocessing
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import List, Optional

import pypdf

# ─── Limites (constantes nombradas, nunca numeros magicos sueltos) ─────────
MAX_PAGINAS_PDF = 10
# Tiempo maximo de procesamiento REAL - aplicado con un PROCESO APARTE
# (multiprocessing.Process.terminate(), no solo un timeout de asyncio
# alrededor de un hilo) porque un hilo de Python no se puede matar de
# verdad si queda atorado en codigo C/puro-Python de un PDF malicioso
# (ej. un "PDF bomb" con streams anidados) - ver extraer_analisis() abajo.
TIEMPO_MAX_LECTURA_SEGUNDOS = 5


class TipoDocumentoDetectado(str, Enum):
    ACUSE_ANUAL = "ACUSE_ANUAL"
    OPINION_CUMPLIMIENTO = "OPINION_CUMPLIMIENTO"
    NO_RECONOCIDO = "NO_RECONOCIDO"


@dataclass
class DatosExtraidos:
    rfc: Optional[str] = None
    ejercicio: Optional[int] = None
    tipo_declaracion: Optional[str] = None  # 'normal'|'complementaria'
    numero_complementaria: Optional[int] = None
    numero_operacion: Optional[str] = None
    fecha_presentacion: Optional[datetime] = None
    saldo_a_favor: Optional[Decimal] = None
    cantidad_a_cargo: Optional[Decimal] = None
    cantidad_a_pagar: Optional[Decimal] = None
    ingresos_que_declara: List[str] = field(default_factory=list)

    def num_campos_extraidos(self) -> int:
        """Cuenta cuantos de los 9 campos escalares (sin contar la lista
        de ingresos) se lograron extraer - usado SOLO para reportar en
        V3 (nunca se exponen los valores ahi, solo el conteo)."""
        campos = [
            self.rfc, self.ejercicio, self.tipo_declaracion,
            self.numero_operacion, self.fecha_presentacion,
            self.saldo_a_favor, self.cantidad_a_cargo, self.cantidad_a_pagar,
        ]
        return sum(1 for c in campos if c is not None) + (1 if self.ingresos_que_declara else 0)


@dataclass
class ResultadoAnalisis:
    tipo_detectado: TipoDocumentoDetectado
    datos: Optional[DatosExtraidos] = None
    # Mensaje SEGURO para mostrar al usuario (nunca expone detalle interno
    # de la excepcion real) - solo se llena si tipo_detectado no trae
    # datos utilizables.
    error_lectura: Optional[str] = None


def _normalizar(texto: str) -> str:
    """Mayusculas, sin acentos, espacios colapsados - tolerante a
    variaciones tipograficas reales entre generaciones de PDF del SAT
    (mismo marcador puede venir con o sin acento segun la version del
    sistema que genero el acuse)."""
    forma = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(c for c in forma if not unicodedata.combining(c))
    return re.sub(r"[ \t]+", " ", sin_acentos.upper())


def _extraer_texto_paginas_sync(contenido: bytes) -> List[str]:
    """Corre DENTRO del proceso aparte (ver extraer_analisis) - nunca se
    llama directo desde el endpoint. Lanza ValueError si excede
    MAX_PAGINAS_PDF o si pypdf no puede ni abrir el archivo."""
    try:
        lector = pypdf.PdfReader(io.BytesIO(contenido))
    except Exception as e:
        raise ValueError(f"PDF corrupto o ilegible: {e}")
    if len(lector.pages) > MAX_PAGINAS_PDF:
        raise ValueError(f"El PDF tiene mas de {MAX_PAGINAS_PDF} paginas")
    paginas = []
    for pagina in lector.pages:
        try:
            paginas.append(pagina.extract_text() or "")
        except Exception:
            paginas.append("")  # una pagina individual ilegible no tumba el documento completo
    return paginas


def _worker_extraer_texto(contenido: bytes, cola: "multiprocessing.Queue") -> None:
    """Punto de entrada del proceso aparte - nunca deja escapar una
    excepcion sin capturar hacia multiprocessing (eso solo tumbaria el
    proceso hijo sin avisar al padre; aqui se reporta explicito)."""
    try:
        paginas = _extraer_texto_paginas_sync(contenido)
        cola.put(("ok", paginas))
    except Exception as e:
        cola.put(("error", str(e)))


def _extraer_texto_con_limite_sync(contenido: bytes) -> Optional[List[str]]:
    """Orquesta el proceso aparte con timeout DURO real: si
    TIEMPO_MAX_LECTURA_SEGUNDOS se cumple sin resultado, el proceso se
    TERMINA de verdad (terminate(), no solo se abandona un hilo en
    segundo plano) - a diferencia de un ThreadPoolExecutor con timeout,
    que NO puede detener trabajo Python ya en curso. Devuelve None ante
    timeout, crash del proceso hijo, o cualquier error de lectura -
    nunca lanza.

    BUG REAL encontrado al correr la suite completa (V1): la primera
    version de esta funcion hacia proceso.join(timeout=...) ANTES de
    leer la cola - eso es un deadlock CLASICO de multiprocessing: si el
    texto extraido supera el buffer del pipe interno de la Queue
    (tipicamente 64KB en Linux, facil de superar con varias paginas de
    texto real), el proceso hijo se queda bloqueado en cola.put()
    esperando que alguien vacie el pipe, mientras el padre esta
    bloqueado en proceso.join() esperando a que el hijo termine - nunca
    pasa. Corregido: se lee la cola PRIMERO (cola.get(timeout=...), que
    ademas de traer el resultado va vaciando el pipe en el momento
    correcto), y solo despues se hace join() (ya sabiendo que el hijo
    termino de trabajar, join aqui es solo limpieza del proceso
    zombie)."""
    # Contexto "spawn" explícito (reporte 189b, F5) - el default de
    # multiprocessing en Linux es "fork", que clona el proceso completo
    # (incluye el event loop de asyncio/uvicorn ya en marcha, sus file
    # descriptors, threads internos de asyncpg, etc.) - "spawn" arranca un
    # intérprete de Python NUEVO y limpio para el hijo, sin arrastrar nada
    # de eso. Mas lento de arrancar que fork, pero mas seguro dentro de un
    # proceso async con conexiones de red/BD abiertas (fork despues de
    # threads/event loops activos es una fuente conocida de deadlocks y
    # file descriptors corruptos en el hijo - no es hipotetico, es el
    # motivo documentado por el propio equipo de CPython para que "spawn"
    # sea el default en macOS/Windows desde Python 3.8).
    ctx = multiprocessing.get_context("spawn")
    cola: multiprocessing.Queue = ctx.Queue()
    proceso = ctx.Process(target=_worker_extraer_texto, args=(contenido, cola))
    proceso.start()
    try:
        estado, resultado = cola.get(timeout=TIEMPO_MAX_LECTURA_SEGUNDOS)
    except Exception:
        # queue.Empty (timeout real) o cualquier otro fallo al leer la
        # cola - en ambos casos el proceso se considera colgado/fallido.
        proceso.terminate()
        proceso.join(timeout=1)
        if proceso.is_alive():
            proceso.kill()  # SIGKILL como ultimo recurso si terminate() (SIGTERM) no basto
        proceso.join()
        return None

    proceso.join(timeout=1)  # limpieza - ya sabemos que puso su resultado, esto no deberia tardar
    if proceso.is_alive():
        proceso.terminate()
        proceso.join()

    if estado == "error":
        return None
    return resultado


# ─── Marcadores de clasificacion (sobre texto YA normalizado) ─────────────
_MARCADOR_OPINION = "OPINION DEL CUMPLIMIENTO"
_MARCADOR_ACUSE_RECIBO = "ACUSE DE RECIBO"
_MARCADOR_DECLARACION_EJERCICIO = "DECLARACION DEL EJERCICIO"


def _clasificar(texto_normalizado: str) -> TipoDocumentoDetectado:
    # OPINION primero a proposito: un falso negativo aqui (tratar una
    # opinion de cumplimiento como acuse) es peor que el caso inverso -
    # rechazar de forma segura gana empates.
    if _MARCADOR_OPINION in texto_normalizado:
        return TipoDocumentoDetectado.OPINION_CUMPLIMIENTO
    if _MARCADOR_ACUSE_RECIBO in texto_normalizado and _MARCADOR_DECLARACION_EJERCICIO in texto_normalizado:
        return TipoDocumentoDetectado.ACUSE_ANUAL
    return TipoDocumentoDetectado.NO_RECONOCIDO


# ─── Extraccion de campos del acuse ────────────────────────────────────────
# Soporta AMBOS formatos conocidos de persona fisica (ver reporte 189,
# CONTEXTO): el reciente ("RFC:", "Número de operación:") y el de 2013
# ("R.F.C. :", "Número de Operación:", "IMPUESTOS QUE DECLARA", "ANEXOS
# QUE PRESENTA"). Persona moral: MISMOS marcadores asumidos (no hay
# muestra real para verificar - NO VERIFICADO, documentado en el
# entregable).
#
# Los patrones toleran puntos/espacios opcionales entre letras (RFC vs
# R.F.C., con o sin espacio antes de ":") precisamente para cubrir las 2
# variantes con una sola expresion regular en vez de duplicar logica.
_RE_RFC = re.compile(r"R\.?\s*F\.?\s*C\.?\s*:?\s*([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})")
_RE_NUM_OPERACION = re.compile(r"NUMERO\s+DE\s+OPERACI[OÓ]N\s*:?\s*([A-Z0-9]{6,30})")
_RE_EJERCICIO_TITULO = re.compile(rf"{_MARCADOR_DECLARACION_EJERCICIO}\s+(\d{{4}})")
_RE_EJERCICIO_GENERICO = re.compile(r"EJERCICIO\s*:?\s*(\d{4})")
_RE_FECHA_PRESENTACION = re.compile(
    r"FECHA\s+Y?\s*HORA\s+DE\s+PRESENTACI[OÓ]N\s*:?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})[^\d]{0,5}(\d{1,2}:\d{2}(?::\d{2})?)"
)
_RE_FECHA_SOLA = re.compile(r"FECHA\s+DE\s+PRESENTACI[OÓ]N\s*:?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})")
# Formato del monto: el grupo de miles (",NNN") y los centavos (".NN") son
# AMBOS opcionales - hallazgo real del reporte 189b (F2), verificado contra
# los 6 acuses reales de RAHP7112093H0: pypdf extrae "CANTIDAD A CARGO: 0"
# (entero, sin ".00") cuando el monto es cero, y el separador de miles solo
# aparece si el monto lo amerita (ej. "12,345" sin decimales visibles en el
# texto extraido) - exigir ambos siempre (como antes) dejaba estos montos
# reales sin extraer. "SALDO" antes de "A FAVOR" tambien es opcional: el
# desglose por concepto de los acuses reales usa la etiqueta desnuda
# "A FAVOR:" (sin "SALDO"), no solo la fila resumen "SALDO A FAVOR:".
_RE_MONTO = r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)"
_RE_SALDO_FAVOR = re.compile(rf"(?:SALDO\s+)?A\s+FAVOR\s*:?\s*{_RE_MONTO}")
_RE_CANTIDAD_CARGO = re.compile(rf"CANTIDAD\s+A\s+CARGO\s*:?\s*{_RE_MONTO}")
_RE_CANTIDAD_PAGAR = re.compile(rf"CANTIDAD\s+A\s+PAGAR\s*:?\s*{_RE_MONTO}")
_RE_COMPLEMENTARIA = re.compile(r"COMPLEMENTARIA")
_RE_NUM_COMPLEMENTARIA = re.compile(r"(?:NUMERO|NO\.?)\s+DE\s+COMPLEMENTARIA\s*:?\s*(\d+)")

# Encabezados de la lista de ingresos/impuestos - el formato reciente usa
# "INGRESOS QUE DECLARA", el de 2013 usa "IMPUESTOS QUE DECLARA". Ambos
# terminan (empiricamente, sin fuente oficial que lo confirme - ver
# "NO VERIFICADO" en el entregable) donde empieza la siguiente seccion
# conocida: "ANEXOS QUE PRESENTA" (2013) o una linea en blanco seguida de
# otro encabezado en mayusculas (reciente, heuristica mas debil).
_RE_INICIO_LISTA = re.compile(r"(?:INGRESOS|IMPUESTOS)\s+QUE\s+DECLARA")
_RE_FIN_LISTA = re.compile(r"ANEXOS\s+QUE\s+PRESENTA")


def _parsear_decimal(texto: Optional[str]) -> Optional[Decimal]:
    if not texto:
        return None
    try:
        return Decimal(texto.replace(",", ""))
    except InvalidOperation:
        return None


def _parsear_fecha(fecha_str: str, hora_str: Optional[str]) -> Optional[datetime]:
    fecha_str = fecha_str.replace("-", "/")
    partes = fecha_str.split("/")
    if len(partes) != 3:
        return None
    dia, mes, anio = partes
    if len(anio) == 2:
        anio = "20" + anio
    hora_str = hora_str or "00:00"
    try:
        return datetime.strptime(f"{dia}/{mes}/{anio} {hora_str}", "%d/%m/%Y %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(f"{dia}/{mes}/{anio} {hora_str}", "%d/%m/%Y %H:%M")
        except ValueError:
            return None


def _extraer_lista_ingresos(texto_normalizado: str, texto_original: str) -> List[str]:
    """Extrae la lista de renglones entre el encabezado de la seccion y
    el siguiente marcador conocido - trabaja sobre el texto ORIGINAL
    (preservando mayusculas/minusculas reales de cada renglon, ej.
    "Sueldos, salarios y asimilados" tal como aparece en el acuse) mapeando
    las posiciones encontradas en el texto normalizado."""
    m_inicio = _RE_INICIO_LISTA.search(texto_normalizado)
    if not m_inicio:
        return []
    m_fin = _RE_FIN_LISTA.search(texto_normalizado, m_inicio.end())
    fin = m_fin.start() if m_fin else min(len(texto_normalizado), m_inicio.end() + 2000)
    # Mapeo aproximado por proporcion de longitud (normalizar no cambia
    # el conteo de caracteres de forma significativa salvo acentos, que
    # son 1 char igual en ambas cadenas tras NFKD) - suficiente para una
    # lista de texto plano, no se necesita un mapeo caracter-a-caracter
    # exacto.
    fragmento = texto_original[m_inicio.end():fin] if fin <= len(texto_original) else texto_original[m_inicio.end():]
    renglones = [r.strip(" \t-•") for r in fragmento.splitlines()]
    return [r for r in renglones if r and len(r) > 2]


def _extraer_datos_acuse(texto_original: str) -> DatosExtraidos:
    normalizado = _normalizar(texto_original)
    datos = DatosExtraidos()

    m = _RE_RFC.search(normalizado)
    if m:
        datos.rfc = m.group(1)

    m = _RE_EJERCICIO_TITULO.search(normalizado) or _RE_EJERCICIO_GENERICO.search(normalizado)
    if m:
        datos.ejercicio = int(m.group(1))

    if _RE_COMPLEMENTARIA.search(normalizado):
        datos.tipo_declaracion = "complementaria"
        m = _RE_NUM_COMPLEMENTARIA.search(normalizado)
        datos.numero_complementaria = int(m.group(1)) if m else None
    else:
        datos.tipo_declaracion = "normal"

    m = _RE_NUM_OPERACION.search(normalizado)
    if m:
        datos.numero_operacion = m.group(1)

    m = _RE_FECHA_PRESENTACION.search(normalizado)
    if m:
        datos.fecha_presentacion = _parsear_fecha(m.group(1), m.group(2))
    else:
        m = _RE_FECHA_SOLA.search(normalizado)
        if m:
            datos.fecha_presentacion = _parsear_fecha(m.group(1), None)

    m = _RE_SALDO_FAVOR.search(normalizado)
    datos.saldo_a_favor = _parsear_decimal(m.group(1)) if m else None
    m = _RE_CANTIDAD_CARGO.search(normalizado)
    datos.cantidad_a_cargo = _parsear_decimal(m.group(1)) if m else None
    m = _RE_CANTIDAD_PAGAR.search(normalizado)
    datos.cantidad_a_pagar = _parsear_decimal(m.group(1)) if m else None

    datos.ingresos_que_declara = _extraer_lista_ingresos(normalizado, texto_original)

    return datos


def analizar_pdf(contenido: bytes) -> ResultadoAnalisis:
    """Punto de entrada UNICO de este modulo - SINCRONO a proposito (el
    endpoint que lo use debe envolverlo en asyncio.to_thread, ver main.py,
    para no bloquear el event loop mientras multiprocessing.Process.join
    espera hasta TIEMPO_MAX_LECTURA_SEGUNDOS). Nunca lanza - cualquier
    fallo de lectura se traduce a NO_RECONOCIDO con error_lectura."""
    paginas = _extraer_texto_con_limite_sync(contenido)
    if paginas is None:
        return ResultadoAnalisis(
            tipo_detectado=TipoDocumentoDetectado.NO_RECONOCIDO,
            error_lectura="No se pudo leer el documento",
        )

    texto_completo = "\n".join(paginas)
    if not texto_completo.strip():
        # Capa de texto vacia (ej. PDF escaneado como imagen, sin OCR) -
        # NO_RECONOCIDO limpio, sin fingir un error de lectura que no
        # ocurrio (el PDF SI se abrio bien, solo no tiene texto).
        return ResultadoAnalisis(tipo_detectado=TipoDocumentoDetectado.NO_RECONOCIDO)

    normalizado = _normalizar(texto_completo)
    tipo = _clasificar(normalizado)

    if tipo == TipoDocumentoDetectado.OPINION_CUMPLIMIENTO:
        return ResultadoAnalisis(tipo_detectado=tipo)
    if tipo == TipoDocumentoDetectado.NO_RECONOCIDO:
        return ResultadoAnalisis(tipo_detectado=tipo)

    datos = _extraer_datos_acuse(texto_completo)
    return ResultadoAnalisis(tipo_detectado=tipo, datos=datos)
