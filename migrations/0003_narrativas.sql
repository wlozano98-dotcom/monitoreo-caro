-- Qué aspecto de la respuesta evalúa la pieza y qué idea transmite (para agrupar narrativas).
ALTER TABLE piezas ADD COLUMN aspecto TEXT;
ALTER TABLE piezas ADD COLUMN idea TEXT;

-- Narrativas agrupadas por Gemini (las de la última corrida son las vigentes).
CREATE TABLE IF NOT EXISTS narrativas (
  creado TEXT PRIMARY KEY,
  datos TEXT NOT NULL
);
