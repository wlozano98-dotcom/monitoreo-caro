-- Máximo caudal de cada año (1980-hoy) por tramo de río GEOGLOWS: la historia no cambia, se baja una vez por tramo.
-- Sirve para decir qué tan rara es la crecida del escenario central (lluvias.py).
CREATE TABLE IF NOT EXISTS rios_maximos (
  comid INTEGER PRIMARY KEY,
  maximos TEXT NOT NULL
);
