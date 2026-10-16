"""Lectores mínimos con la biblioteca estándar: texto de un PDF (los SitRep de la SNGR, hechos en Word) e imágenes PNG
(las capas de Copernicus). Sin dependencias, para que corran igual en la Mac y en GitHub Actions."""

import re
import struct
import zlib

# ---------------------------------------------------------------- PDF


def _objetos(b):
    obj = {int(m.group(1)): m.group(2) for m in re.finditer(rb"(\d+)\s+0\s+obj(.*?)endobj", b, re.S)}
    # Objetos guardados dentro de flujos de objetos (/ObjStm)
    for cuerpo in list(obj.values()):
        if b"/ObjStm" not in cuerpo:
            continue
        d = _flujo(cuerpo)
        primero = int(re.search(rb"/First\s+(\d+)", cuerpo).group(1))
        cab = d[:primero].split()
        pares = [(int(cab[i]), int(cab[i + 1])) for i in range(0, len(cab), 2)]
        for k, (num, desde) in enumerate(pares):
            hasta = pares[k + 1][1] if k + 1 < len(pares) else len(d) - primero
            obj.setdefault(num, d[primero + desde:primero + hasta])
    return obj


def _flujo(cuerpo):
    m = re.search(rb"stream\r?\n", cuerpo)
    if not m:
        return b""
    d = cuerpo[m.end():]
    d = d[:d.rfind(b"endstream")]
    if b"/FlateDecode" in cuerpo[:m.start()]:
        return zlib.decompressobj().decompress(d)
    return d


def _ref(cuerpo, clave):
    m = re.search(rb"/" + clave + rb"\s+(\d+)\s+0\s+R", cuerpo)
    return int(m.group(1)) if m else None


def _cmap(texto):
    """Tabla ToUnicode: código de la fuente -> letra."""
    mapa = {}
    for bloque in re.findall(rb"beginbfchar(.*?)endbfchar", texto, re.S):
        for a, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", bloque):
            mapa[int(a, 16)] = bytes.fromhex(c.decode()).decode("utf-16-be", "replace")
    for bloque in re.findall(rb"beginbfrange(.*?)endbfrange", texto, re.S):
        for a, z, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", bloque):
            for k in range(int(a, 16), int(z, 16) + 1):
                mapa[k] = chr(int(c, 16) + k - int(a, 16))
    return mapa


def _fuentes(pagina, obj):
    r = _ref(pagina, b"Resources")
    recursos = obj[r] if r else pagina
    m = re.search(rb"/Font\s*(<<.*?>>|\d+\s+0\s+R)", recursos, re.S)
    if not m:
        return {}
    d = m.group(1)
    if d.endswith(b"R"):
        d = obj[int(d.split()[0])]
    salida = {}
    for nombre, num in re.findall(rb"/(\w+)\s+(\d+)\s+0\s+R", d):
        f = obj.get(int(num), b"")
        tu = _ref(f, b"ToUnicode")
        salida[nombre] = {"doble": b"/Type0" in f, "mapa": _cmap(_flujo(obj[tu])) if tu else {}}
    return salida


_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}


def _cadenas(op):
    """Las cadenas (...) y <...> de un operando Tj/TJ; None marca un hueco grande (un espacio)."""
    salida, i = [], 0
    while i < len(op):
        c = op[i:i + 1]
        if c == b"(":
            prof, j, buf = 1, i + 1, bytearray()
            while j < len(op) and prof:
                ch = op[j:j + 1]
                if ch == b"\\":
                    sig = op[j + 1:j + 2]
                    if sig in _ESCAPES:
                        buf += _ESCAPES[sig]
                        j += 2
                    elif sig.isdigit():
                        k = j + 1
                        while k < j + 4 and op[k:k + 1].isdigit():
                            k += 1
                        buf.append(int(op[j + 1:k], 8) & 255)
                        j = k
                    else:
                        buf += sig
                        j += 2
                    continue
                if ch == b"(":
                    prof += 1
                elif ch == b")":
                    prof -= 1
                    if not prof:
                        break
                buf += ch
                j += 1
            salida.append(bytes(buf))
            i = j + 1
        elif c == b"<":
            j = op.index(b">", i)
            hexa = re.sub(rb"\s", b"", op[i + 1:j]).decode()
            salida.append(bytes.fromhex(hexa + "0" * (len(hexa) % 2)))
            i = j + 1
        elif c == b"-" or c.isdigit():
            m = re.match(rb"-?[\d.]+", op[i:])
            if m and float(m.group()) < -200:
                salida.append(None)
            i += len(m.group()) if m else 1
        else:
            i += 1
    return salida


_OPERADORES = re.compile(
    rb"/(\w+)\s+[\d.]+\s+Tf"
    rb"|([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+Tm"
    rb"|([-\d.]+)\s+([-\d.]+)\s+T[dD]"
    rb"|(\[(?:[^\]\\]|\\.)*\]|\((?:[^)\\]|\\.)*\)|<[0-9A-Fa-f\s]*>)\s*(?:TJ|Tj)", re.S)


def texto_pdf(datos):
    """Texto de un PDF por líneas (junta lo que está a la misma altura), página por página."""
    obj = _objetos(datos)
    lineas = []
    for n in sorted(n for n, c in obj.items() if re.search(rb"/Type\s*/Page[^s]", c)):
        pagina = obj[n]
        fuentes = _fuentes(pagina, obj)
        contenido = re.search(rb"/Contents\s*(\[.*?\]|\d+\s+0\s+R)", pagina, re.S).group(1)
        flujo = b"".join(_flujo(obj[int(x)]) for x in re.findall(rb"(\d+)\s+0\s+R", contenido))
        piezas, fuente, x, y = [], None, 0.0, 0.0
        for m in _OPERADORES.finditer(flujo):
            if m.group(1):
                fuente = fuentes.get(m.group(1), {"doble": False, "mapa": {}})
            elif m.group(2):
                x, y = float(m.group(6)), float(m.group(7))
            elif m.group(8):
                x, y = x + float(m.group(8)), y + float(m.group(9))
            elif m.group(10):
                t = ""
                for s in _cadenas(m.group(10)):
                    if s is None:
                        t += " "
                    elif fuente and fuente["doble"]:
                        t += "".join(fuente["mapa"].get(int.from_bytes(s[k:k + 2], "big"), "") for k in range(0, len(s) - 1, 2))
                    elif fuente and fuente["mapa"]:
                        t += "".join(fuente["mapa"].get(ch, chr(ch)) for ch in s)
                    else:
                        t += s.decode("cp1252", "replace")
                piezas.append((round(-y), x, t))
        filas = {}
        for yy, xx, t in piezas:
            clave = next((k for k in filas if abs(k - yy) <= 2), yy)
            filas.setdefault(clave, []).append((xx, t))
        lineas += [" ".join(t for _, t in sorted(filas[k])).strip() for k in sorted(filas)]
    return [l for l in lineas if l]


# ---------------------------------------------------------------- PNG


def png(datos):
    """PNG de 8 bits -> (ancho, alto, paleta o None, filas de bytes, canales). Con paleta, cada byte es un índice."""
    i, partes, idat = 8, {}, b""
    while i < len(datos):
        n = struct.unpack(">I", datos[i:i + 4])[0]
        tipo, d = datos[i + 4:i + 8], datos[i + 8:i + 8 + n]
        i += 12 + n
        if tipo == b"IDAT":
            idat += d
        else:
            partes[tipo] = d
    ancho, alto, bits, color = struct.unpack(">IIBB", partes[b"IHDR"][:10])
    canales = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    # Con paleta de 1, 2 o 4 bits, varios píxeles van en un byte: se desempacan al final de cada fila
    crudo, paso = zlib.decompress(idat), (ancho * canales * bits + 7) // 8
    canales_filtro = max(1, canales * bits // 8)
    filas, previa, k = [], bytearray(paso), 0
    for _ in range(alto):
        filtro, linea = crudo[k], bytearray(crudo[k + 1:k + 1 + paso])
        k += 1 + paso
        if filtro:
            for x in range(paso):
                a = linea[x - canales_filtro] if x >= canales_filtro else 0
                arriba = previa[x]
                c = previa[x - canales_filtro] if x >= canales_filtro else 0
                if filtro == 1:
                    linea[x] = (linea[x] + a) & 255
                elif filtro == 2:
                    linea[x] = (linea[x] + arriba) & 255
                elif filtro == 3:
                    linea[x] = (linea[x] + ((a + arriba) >> 1)) & 255
                else:
                    p = a + arriba - c
                    pa, pb, pc = abs(p - a), abs(p - arriba), abs(p - c)
                    linea[x] = (linea[x] + (a if pa <= pb and pa <= pc else arriba if pb <= pc else c)) & 255
        previa = linea
        if bits < 8:
            mascara = (1 << bits) - 1
            linea = bytearray((linea[x * bits // 8] >> (8 - bits - (x * bits) % 8)) & mascara for x in range(ancho))
        filas.append(bytes(linea))
    paleta = None
    if color == 3:
        pal, alfa = partes[b"PLTE"], partes.get(b"tRNS", b"")
        paleta = [(pal[3 * j], pal[3 * j + 1], pal[3 * j + 2], alfa[j] if j < len(alfa) else 255) for j in range(len(pal) // 3)]
    return ancho, alto, paleta, filas, canales
