-- Peso por alcance (escala comprimida, se calcula en monitor.py): 10 vistas = 1, 1.000 = 3 (una nota de medio), 100.000 = 5.
ALTER TABLE piezas ADD COLUMN peso REAL;
-- 1 si alguien del equipo corrigió la pieza a mano: la IA ya no la vuelve a clasificar.
ALTER TABLE piezas ADD COLUMN corregido INTEGER;

-- Correcciones hechas desde el tablero (se aplican directo a piezas; aquí queda el historial para deshacer y para
-- dárselas a Gemini como ejemplos).
CREATE TABLE IF NOT EXISTS correcciones (
  creado TEXT NOT NULL,
  pieza TEXT NOT NULL,
  campo TEXT NOT NULL,
  antes TEXT,
  despues TEXT,
  quien TEXT
);
CREATE INDEX IF NOT EXISTS correcciones_creado ON correcciones (creado);

-- Hitos que marca la rutina de Claude (con las piezas que los sostienen).
CREATE TABLE IF NOT EXISTS hitos (
  dia TEXT NOT NULL,
  titulo TEXT NOT NULL,
  ids TEXT NOT NULL,
  creado TEXT NOT NULL,
  PRIMARY KEY (dia, titulo)
);
