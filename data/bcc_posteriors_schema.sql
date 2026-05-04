-- BCC-HIL persistent posteriors (Phase I).
-- One Beta(alpha, beta) per Phase 1 product category.
-- Updated incrementally from Telegram approve / reject callbacks.
-- Read once per pipeline tick by the "Read BCC Posteriors" node.

CREATE TABLE IF NOT EXISTS private.bcc_posteriors (
  category    TEXT PRIMARY KEY,
  alpha       REAL NOT NULL DEFAULT 1.0,
  beta        REAL NOT NULL DEFAULT 1.0,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  private.bcc_posteriors      IS 'Beta(alpha,beta) posterior over P(approve|category) for BCC-HIL feedback calibration.';
COMMENT ON COLUMN private.bcc_posteriors.alpha IS 'Beta shape; +1 per approval observation in this category.';
COMMENT ON COLUMN private.bcc_posteriors.beta  IS 'Beta shape; +1 per rejection observation in this category.';

-- Seed the 13 Phase 1 categories so the read node always returns a row
-- and the cold-start formula (w = 0 when alpha = beta = 1) falls back to
-- the raw Phase 4 score until real feedback accumulates.
INSERT INTO private.bcc_posteriors (category, alpha, beta) VALUES
  ('electronics',           1.0, 1.0),
  ('fashion',               1.0, 1.0),
  ('home',                  1.0, 1.0),
  ('fitness',               1.0, 1.0),
  ('beauty',                1.0, 1.0),
  ('accessories',           1.0, 1.0),
  ('automotive',            1.0, 1.0),
  ('baby_and_kids',         1.0, 1.0),
  ('pets',                  1.0, 1.0),
  ('office_and_stationery', 1.0, 1.0),
  ('health_and_medical',    1.0, 1.0),
  ('tools_and_hardware',    1.0, 1.0),
  ('grocery_and_food',      1.0, 1.0)
ON CONFLICT (category) DO NOTHING;
