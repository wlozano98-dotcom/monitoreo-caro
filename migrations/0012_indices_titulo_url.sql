-- La cobertura del vigilante y el puente agenda->piezas buscan cada titular en piezas por título o URL.
-- Sin índice cada búsqueda recorría toda la tabla: el 20 oct 2026 se acabaron los 5 millones de lecturas diarias de D1.
CREATE INDEX IF NOT EXISTS piezas_titulo ON piezas (titulo);
CREATE INDEX IF NOT EXISTS piezas_url ON piezas (url);
