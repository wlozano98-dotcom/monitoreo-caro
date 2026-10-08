-- Cada pieza recogida: una noticia, un tweet, un comentario, un video.
CREATE TABLE IF NOT EXISTS piezas (
  id TEXT PRIMARY KEY,              -- huella (sha1) de la URL o del id de la red
  fuente TEXT NOT NULL,             -- medios | youtube | x | tiktok | facebook
  medio TEXT,                       -- nombre del medio o cuenta que publica
  url TEXT,
  titulo TEXT,
  texto TEXT,
  autor TEXT,
  fecha TEXT,                       -- ISO 8601 UTC de publicación
  recogido TEXT NOT NULL,           -- ISO 8601 UTC
  interacciones INTEGER DEFAULT 0,  -- likes + comentarios + compartidos (redes)
  padre TEXT,                       -- URL de la publicación comentada (comentarios)
  consulta TEXT,                    -- qué búsqueda la trajo
  clasificado INTEGER DEFAULT 0,    -- 0 pendiente, 1 hecho, -1 falló
  relevante INTEGER,
  sobre TEXT,                       -- carolina | secretaria | nino
  tono TEXT,                        -- positivo | neutro | critico
  tema TEXT,
  provincia TEXT,
  alerta INTEGER DEFAULT 0,
  resumen TEXT
);
CREATE INDEX IF NOT EXISTS piezas_fecha ON piezas(fecha);
CREATE INDEX IF NOT EXISTS piezas_pendientes ON piezas(clasificado);

-- Resumen del día escrito por Gemini (uno por fecha de Ecuador, se reescribe en cada corrida).
CREATE TABLE IF NOT EXISTS resumenes (
  fecha TEXT PRIMARY KEY,
  texto TEXT NOT NULL,
  creado TEXT NOT NULL
);

-- Registro de corridas para ver en el tablero si todo está funcionando.
CREATE TABLE IF NOT EXISTS corridas (
  inicio TEXT PRIMARY KEY,
  fin TEXT,
  detalle TEXT
);
