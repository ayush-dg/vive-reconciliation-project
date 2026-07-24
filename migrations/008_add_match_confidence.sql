-- 008_add_match_confidence.sql
-- Adds a match_confidence score to both gold_matched_invoices and
-- gold_exceptions (see src/matching/engine.py's MATCH_CONFIDENCE /
-- EXCEPTION_MATCH_CONFIDENCE tables). For gold_matched_invoices it scores
-- how reliable the match itself is (exact invoice + exact amount is far
-- more trustworthy than an RO-number match on a fuzzy amount); for
-- gold_exceptions it scores how confident the system is that the row is
-- a genuine exception rather than a matching error. Nullable -- rows
-- written before this change (and a few exception write sites not yet
-- covered, e.g. DUPLICATE_RECORD) simply have no score yet.

ALTER TABLE gold_matched_invoices ADD COLUMN match_confidence REAL;
ALTER TABLE gold_exceptions ADD COLUMN match_confidence REAL;
