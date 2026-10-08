-- Última vez que se pidió cada red a Apify (para no pasarse del crédito gratis).
CREATE TABLE IF NOT EXISTS ultimas (
  red TEXT PRIMARY KEY,
  cuando TEXT NOT NULL
);
