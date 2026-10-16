-- SitRep provinciales de la SNGR (emergencias.py): cada PDF se lee una vez; trae personas por cantón.
CREATE TABLE IF NOT EXISTS sitrep_prov (
  url TEXT PRIMARY KEY,
  datos TEXT NOT NULL
);
