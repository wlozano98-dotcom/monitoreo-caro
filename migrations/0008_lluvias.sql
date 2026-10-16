-- Lluvias y ríos (lluvias.py): una foto por corrida con la decisión por cantón (preparar / vigilar) y sus razones.
-- Se guardan 60 días para comparar después qué alertas terminaron en noticias de inundación.
CREATE TABLE IF NOT EXISTS lluvias (
  creado TEXT PRIMARY KEY,
  datos TEXT NOT NULL
);
