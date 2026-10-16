-- Dónde ya hay emergencia (emergencias.py): lo que dice cada SitRep de la SNGR por cantón (se lee el PDF una vez)
-- y el agua que Copernicus detecta por satélite cada día (km² por cantón).
CREATE TABLE IF NOT EXISTS sitrep (
  numero INTEGER PRIMARY KEY,
  datos TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agua_satelite (
  fecha TEXT PRIMARY KEY,
  datos TEXT NOT NULL
);
