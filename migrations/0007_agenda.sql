-- Agenda nacional: todos los titulares de los medios del país (no solo los de El Niño), para ver qué tan alto está
-- El Niño en la conversación. `dia` = fecha de Ecuador. `tema` y `nino` los pone la última agrupación que lo vio.
CREATE TABLE IF NOT EXISTS titulares (
  id TEXT PRIMARY KEY,
  medio TEXT,
  titulo TEXT NOT NULL,
  url TEXT,
  fecha TEXT NOT NULL,
  dia TEXT NOT NULL,
  recogido TEXT NOT NULL,
  tema TEXT,
  nino INTEGER
);
CREATE INDEX IF NOT EXISTS titulares_fecha ON titulares (fecha);
CREATE INDEX IF NOT EXISTS titulares_dia ON titulares (dia);

-- Una foto por corrida: ranking de temas de las últimas 24 h y lo que se busca en Google (las cifras, en Python).
CREATE TABLE IF NOT EXISTS agenda (
  creado TEXT PRIMARY KEY,
  datos TEXT NOT NULL
);
