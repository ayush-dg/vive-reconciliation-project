-- ============================================================================
-- VIVE Reconciliation Rules — Fabric Lakehouse Queries

-- ============================================================================
-- RULE 1 — Direct Match (isolated invoice, no real credit memo, amount ties out)
-- ============================================================================
-- Three allowed shapes, confirmed against a 97-invoice manual cross-check
-- (2026-08-22) -- anything messier than these three falls through to Rule 2/3
-- or UNRESOLVED_NEEDS_REVIEW instead of being force-fit into Rule 1:
--   (a) exactly one line, a charge, matching a Vendor Bill's total
--   (b) exactly one line, a credit, matching a Vendor Bill's total (the
--       charge presumably appeared on an earlier statement outside this
--       file's window -- confirmed as a valid Rule 1 shape, e.g. 9294147)
--   (c) exactly two lines, one charge + one credit of the same amount,
--       matching a Vendor Bill's total (the "duplicate print" pattern)
-- Plus: NetSuite status must be 'B' (Paid In Full).
--
-- CM-exclusion check (revised 2026-08-22): checks whether a "CM<invoice>"
-- line is printed on THIS STATEMENT, not whether one exists anywhere in
-- NetSuite. Reasoning: a same-named NetSuite credit that isn't on this
-- statement is very likely unrelated (per everything proven earlier about
-- credit-memo names being unreliable) and shouldn't disqualify an otherwise
-- clean bill -- e.g. 9424476X1, 9437906, 9462861 all have a real NetSuite
-- credit under their name, but nothing printed on this statement, so they now
-- pass. Conversely, 9412747 prints a CM9412747 line on the statement even
-- though that credit doesn't exist in NetSuite at all -- it's now excluded
-- from Rule 1 (falls to Rule 2/3 or UNRESOLVED_NEEDS_REVIEW instead), since
-- the vendor's own statement is showing related activity for it, real or not.

WITH statement_lines AS (
    SELECT
        INVOICE_NO,
        CASE WHEN INVOICE_NO LIKE 'CM%' THEN SUBSTRING(INVOICE_NO, 3) ELSE INVOICE_NO END AS base_invoice_no,
        CASE WHEN CHARGES IS NOT NULL THEN 'CHARGE'
             WHEN CREDITS IS NOT NULL THEN 'CREDIT'
             ELSE 'EMPTY' END AS line_type,
        TRY_CAST(REPLACE(CHARGES, ',', '') AS DECIMAL(18,2)) AS charge_amt,
        TRY_CAST(REPLACE(CREDITS, ',', '') AS DECIMAL(18,2)) AS credit_amt
    FROM research_schema.fred_beans_statement
),
invoice_shape AS (
    SELECT
        INVOICE_NO,
        MAX(base_invoice_no)                                  AS base_invoice_no,
        COUNT(*)                                              AS line_count,
        SUM(CASE WHEN line_type = 'CHARGE' THEN 1 ELSE 0 END) AS charge_line_count,
        SUM(CASE WHEN line_type = 'CREDIT' THEN 1 ELSE 0 END) AS credit_line_count,
        MAX(charge_amt) AS charge_amt,
        MAX(credit_amt) AS credit_amt
    FROM statement_lines
    GROUP BY INVOICE_NO
),
family_variants AS (
    -- How many distinct INVOICE_NO values share this base, ON THE STATEMENT
    -- itself (not NetSuite). More than 1 means a CM<invoice> line is printed
    -- alongside this invoice -- excludes it from Rule 1 below.
    SELECT base_invoice_no, COUNT(DISTINCT INVOICE_NO) AS variants_on_statement
    FROM statement_lines
    GROUP BY base_invoice_no
),
bill_lookup AS (
    -- Dedupes by tranid before joining. 9437906X2 exists as TWO Vendor Bill
    -- records under different entities (same total, same status) -- a plain
    -- JOIN straight to bronze.netsuite_vendorbill matches both rows and
    -- double-counts this invoice. MAX(...) collapses duplicate-entity rows
    -- to one, assuming (confirmed true here) they agree on total/status.
    SELECT
        tranid,
        MAX(TRY_CAST(total AS DECIMAL(18,2)))         AS total,
        MAX(CASE WHEN status = 'B' THEN 1 ELSE 0 END) AS is_paid_in_full
    FROM bronze.netsuite_vendorbill
    GROUP BY tranid
)
SELECT
    i.INVOICE_NO,
    i.line_count,
    i.charge_amt,
    i.credit_amt,
    bl.tranid AS ns_bill_tranid,
    bl.total  AS ns_bill_total
FROM invoice_shape i
JOIN bill_lookup bl
    ON bl.tranid = i.INVOICE_NO
JOIN family_variants fv
    ON fv.base_invoice_no = i.base_invoice_no
WHERE
    (
        -- (a) single charge line
        (i.line_count = 1 AND i.charge_line_count = 1 AND i.credit_line_count = 0
         AND i.charge_amt = bl.total)
        OR
        -- (b) single credit line matching a Bill (no charge line present at all)
        (i.line_count = 1 AND i.charge_line_count = 0 AND i.credit_line_count = 1
         AND i.credit_amt = bl.total)
        OR
        -- (c) exactly two lines, one charge + one credit, same amount
        (i.line_count = 2 AND i.charge_line_count = 1 AND i.credit_line_count = 1
         AND i.charge_amt = i.credit_amt AND i.charge_amt = bl.total)
    )
    AND bl.is_paid_in_full = 1   -- Paid In Full
    AND fv.variants_on_statement = 1   -- no CM<invoice> line printed on this statement
ORDER BY i.INVOICE_NO;


-- ============================================================================
-- RULE 2 — Credit memo present, statement self-consistent (LHS=RHS), NetSuite confirms paid
-- ============================================================================
-- Deliberately shape-agnostic (unlike Rule 1) -- this is exactly where the
-- messier multi-line invoices from Rule 1's exclusions belong: a real credit
-- memo is involved somewhere in the family, and as long as this invoice's own
-- charges and credits net to zero AND NetSuite confirms the bill is closed,
-- that's two independent signals agreeing -- reconciled, even though the
-- shape is messier than Rule 1 allows. (E.g. 9394216, 9377528, 9403325,
-- 9304198X1, 9396972 all land here once Rule 1 excludes them.)
-- Genuinely messy cases where the sums DON'T tie out (e.g. 9148606, 9189267,
-- 9385899) correctly fall through to UNRESOLVED_NEEDS_REVIEW in the summary
-- query below -- that's expected, not a bug.

-- Shared building block for both 2a and 2b: skip an invoice if IT ALONE
-- (not its family) is a clean 2-line charge+credit pair under the identical
-- invoice number, with no separately-named CM sibling printed anywhere in
-- its family -- that shape is unambiguously Rule 1's territory. Simpler than
-- re-deriving Rule 1's full amount/status logic: this is purely a shape
-- check on the statement's own printed structure, no NetSuite join needed
-- for the exclusion itself. Confirmed safe against this data (2026-08-22):
-- zero same-name 2-line pairs exist where charge=credit but a real bill
-- exists with a DIFFERENT total -- so nothing slips through uncaught by
-- either rule.

WITH statement_lines AS (
    SELECT
        INVOICE_NO,
        CASE WHEN INVOICE_NO LIKE 'CM%' THEN SUBSTRING(INVOICE_NO, 3) ELSE INVOICE_NO END AS base_invoice_no,
        CASE WHEN CHARGES IS NOT NULL THEN 'CHARGE'
             WHEN CREDITS IS NOT NULL THEN 'CREDIT'
             ELSE 'EMPTY' END AS line_type,
        TRY_CAST(REPLACE(CHARGES, ',', '') AS DECIMAL(18,2)) AS charge_amt,
        TRY_CAST(REPLACE(CREDITS, ',', '') AS DECIMAL(18,2)) AS credit_amt
    FROM research_schema.fred_beans_statement
),
statement_agg AS (
    SELECT INVOICE_NO, SUM(charge_amt) AS total_charges, SUM(credit_amt) AS total_credits
    FROM statement_lines
    GROUP BY INVOICE_NO
),
invoice_shape AS (
    SELECT
        INVOICE_NO,
        MAX(base_invoice_no)                                  AS base_invoice_no,
        COUNT(*)                                              AS line_count,
        SUM(CASE WHEN line_type = 'CHARGE' THEN 1 ELSE 0 END) AS charge_line_count,
        SUM(CASE WHEN line_type = 'CREDIT' THEN 1 ELSE 0 END) AS credit_line_count
    FROM statement_lines
    GROUP BY INVOICE_NO
),
family_variants AS (
    SELECT base_invoice_no, COUNT(DISTINCT INVOICE_NO) AS variants_on_statement
    FROM statement_lines
    GROUP BY base_invoice_no
)
SELECT
    s.INVOICE_NO,
    s.total_charges,
    s.total_credits,
    vb.tranid,
    vb.status
FROM statement_agg s
JOIN invoice_shape i ON i.INVOICE_NO = s.INVOICE_NO
JOIN family_variants fv ON fv.base_invoice_no = i.base_invoice_no
JOIN bronze.netsuite_vendorbill vb
    ON vb.tranid = s.INVOICE_NO
WHERE s.total_charges = s.total_credits      -- LHS = RHS
  AND vb.status = 'B'                        -- 'B' = Paid In Full
  AND NOT (i.line_count = 2 AND i.charge_line_count = 1 AND i.credit_line_count = 1
           AND fv.variants_on_statement = 1)  -- skip Rule 1's plain duplicate-pair shape
;


-- ============================================================================
-- RULE 3 — Amount Due explains the charge/credit imbalance
-- ============================================================================
-- FAMILY-level (base invoice + its "CM<invoice>" variant combined), not
-- per-exact-INVOICE_NO -- confirmed necessary by 9437906/CM9437906 and
-- 9444877/CM9444877: the charge sits under the base invoice number, the
-- credit AND the Amount Due sit under the separate CM-prefixed number, so
-- grouping by literal INVOICE_NO put them in different buckets and always
-- left one side NULL. Same fix pattern as Rule 4 (below).
--   9437906:  charge 2,866.05 - CM9437906 credit 662.98   = 2,203.07
--             = CM9437906's own Amount Due (2,203.07) exactly.
--   9444877:  charge   454.02 - CM9444877 credit  50.46   =   403.56
--             = CM9444877's own Amount Due (403.56) exactly.
-- Handles the same trailing-minus-sign quirk in AMOUNT_DUE_1 as elsewhere --
-- it stores negatives as '227.20-', not '-227.20'.
--
-- EXCLUSION (added 2026-08-24): a family only belongs here if the imbalance
-- is genuine -- i.e. NO member of the family already ties out on its own
-- (Rule 2's condition). Without this, a family like 9397934/CM9397934 gets
-- claimed here too: 9397934 ALONE already has charges = credits and a closed
-- bill (a clean Rule 2 match by itself) -- the "imbalance" only appears once
-- CM9397934's unrelated credit is added on top, and its Amount Due just
-- happens to arithmetically explain that self-inflicted gap. That's not the
-- same thing as 9412747, where NO member ties out alone and Amount Due is
-- the only explanation available. Confirmed: 8 of the original 15 families
-- this query returned were exactly this kind of false positive.

WITH statement_lines AS (
    SELECT
        INVOICE_NO,
        CASE WHEN INVOICE_NO LIKE 'CM%' THEN SUBSTRING(INVOICE_NO, 3) ELSE INVOICE_NO END AS base_invoice_no,
        TRY_CAST(REPLACE(CHARGES, ',', '') AS DECIMAL(18,2)) AS charge_amt,
        TRY_CAST(REPLACE(CREDITS, ',', '') AS DECIMAL(18,2)) AS credit_amt,
        CASE WHEN AMOUNT_DUE_1 LIKE '%-'
             THEN CONCAT('-', REPLACE(LEFT(AMOUNT_DUE_1, LEN(AMOUNT_DUE_1) - 1), ',', ''))
             ELSE REPLACE(AMOUNT_DUE_1, ',', '')
        END AS amount_due_1_normalized
    FROM research_schema.fred_beans_statement
),
invoice_agg AS (
    SELECT
        INVOICE_NO,
        MAX(CASE WHEN INVOICE_NO LIKE 'CM%' THEN SUBSTRING(INVOICE_NO, 3) ELSE INVOICE_NO END) AS base_invoice_no,
        SUM(charge_amt) AS total_charges,
        SUM(credit_amt) AS total_credits
    FROM statement_lines
    GROUP BY INVOICE_NO
),
family_agg AS (
    SELECT
        base_invoice_no,
        SUM(charge_amt) AS total_charges,
        SUM(credit_amt) AS total_credits,
        MAX(TRY_CAST(amount_due_1_normalized AS DECIMAL(18,2))) AS amount_due
    FROM statement_lines
    GROUP BY base_invoice_no
),
bill_lookup AS (
    SELECT tranid, MAX(CASE WHEN status = 'B' THEN 1 ELSE 0 END) AS is_paid_in_full
    FROM bronze.netsuite_vendorbill
    GROUP BY tranid
),
credit_lookup AS (
    SELECT tranid, MAX(CASE WHEN TRY_CAST(unapplied AS DECIMAL(18,2)) = 0 THEN 1 ELSE 0 END) AS is_fully_applied
    FROM bronze.netsuite_vendorcredit
    GROUP BY tranid
),
family_has_independent_match AS (
    -- Does ANY member of this family already tie out on its own (Rule 2's
    -- condition), independent of the rest of the family?
    SELECT
        ia.base_invoice_no,
        MAX(CASE WHEN ia.total_charges = ia.total_credits
                       AND (bl.is_paid_in_full = 1 OR cl.is_fully_applied = 1)
                  THEN 1 ELSE 0 END) AS has_independent_match
    FROM invoice_agg ia
    LEFT JOIN bill_lookup bl ON bl.tranid = ia.INVOICE_NO
    LEFT JOIN credit_lookup cl ON cl.tranid = ia.INVOICE_NO
    GROUP BY ia.base_invoice_no
)
SELECT
    fa.base_invoice_no,
    fa.total_charges,
    fa.total_credits,
    fa.amount_due,
    vb.tranid,
    vb.status
FROM family_agg fa
JOIN bronze.netsuite_vendorbill vb
    ON vb.tranid = fa.base_invoice_no
JOIN family_has_independent_match fim
    ON fim.base_invoice_no = fa.base_invoice_no
WHERE fa.total_charges IS NOT NULL
  AND fa.total_credits IS NOT NULL
  AND fa.total_charges <> fa.total_credits          -- fails Rule 1/2's LHS=RHS
  AND fa.amount_due IS NOT NULL
  AND ABS(fa.total_charges - fa.total_credits - fa.amount_due) <= 0.01   -- the gap ties out
  AND vb.status = 'B'                               -- NetSuite confirms closed
  AND fim.has_independent_match = 0;                -- exclude false positives (see note above)



-- ============================================================================
-- RULE 4 — Not found in NetSuite, but statement self-cancels
-- ============================================================================
-- Sums across the whole FAMILY (base invoice + its "CM<invoice>" variant),
-- not just the literal INVOICE_NO string -- confirmed necessary by 8944468:
-- charge 699.57 does NOT equal its own credit 173.68, but 699.57 DOES equal
-- 173.68 + CM8944468's 525.89. The self-cancel math doesn't care whether a
-- credit memo is involved or what it's named -- only that the family's total
-- charges equal its total credits, and that NONE of the family's invoice
-- numbers exist anywhere in NetSuite.

WITH statement_lines AS (
    SELECT
        INVOICE_NO,
        CASE WHEN INVOICE_NO LIKE 'CM%' THEN SUBSTRING(INVOICE_NO, 3) ELSE INVOICE_NO END AS base_invoice_no,
        TRY_CAST(REPLACE(CHARGES, ',', '') AS DECIMAL(18,2)) AS charge_amt,
        TRY_CAST(REPLACE(CREDITS, ',', '') AS DECIMAL(18,2)) AS credit_amt
    FROM research_schema.fred_beans_statement
),
family_agg AS (
    SELECT
        base_invoice_no,
        SUM(charge_amt) AS total_charges,
        SUM(credit_amt) AS total_credits
    FROM statement_lines
    GROUP BY base_invoice_no
)
SELECT
    f.base_invoice_no,
    f.total_charges,
    f.total_credits
FROM family_agg f
WHERE f.total_charges = f.total_credits
  AND NOT EXISTS (
        SELECT 1 FROM statement_lines sl
        JOIN bronze.netsuite_vendorbill vb ON vb.tranid = sl.INVOICE_NO
        WHERE sl.base_invoice_no = f.base_invoice_no
      )
  AND NOT EXISTS (
        SELECT 1 FROM statement_lines sl
        JOIN bronze.netsuite_vendorcredit vc ON vc.tranid = sl.INVOICE_NO
        WHERE sl.base_invoice_no = f.base_invoice_no
      );

-- ============================================================================
-- SUMMARY  — classification counted at FAMILY grain
-- ============================================================================
-- This  collapses each family (base invoice + its CM variant) down to
-- ONE count, matching how Rule 3 and Rule 4's own standalone queries already
-- count (family-level), rather than the invoice-level grain 

WITH statement_lines AS (
    SELECT
        INVOICE_NO,
        CASE WHEN INVOICE_NO LIKE 'CM%' THEN SUBSTRING(INVOICE_NO, 3) ELSE INVOICE_NO END AS base_invoice_no,
        CASE WHEN CHARGES IS NOT NULL THEN 'CHARGE'
             WHEN CREDITS IS NOT NULL THEN 'CREDIT'
             ELSE 'EMPTY' END AS line_type,
        TRY_CAST(REPLACE(CHARGES, ',', '') AS DECIMAL(18,2)) AS charge_amt,
        TRY_CAST(REPLACE(CREDITS, ',', '') AS DECIMAL(18,2)) AS credit_amt,
        CASE WHEN AMOUNT_DUE_1 LIKE '%-'
             THEN CONCAT('-', REPLACE(LEFT(AMOUNT_DUE_1, LEN(AMOUNT_DUE_1) - 1), ',', ''))
             ELSE REPLACE(AMOUNT_DUE_1, ',', '')
        END AS amount_due_1_normalized
    FROM research_schema.fred_beans_statement
),
invoice_shape AS (
    SELECT
        INVOICE_NO,
        MAX(base_invoice_no)                                  AS base_invoice_no,
        COUNT(*)                                              AS line_count,
        SUM(CASE WHEN line_type = 'CHARGE' THEN 1 ELSE 0 END) AS charge_line_count,
        SUM(CASE WHEN line_type = 'CREDIT' THEN 1 ELSE 0 END) AS credit_line_count,
        SUM(charge_amt)                                       AS total_charges,
        SUM(credit_amt)                                       AS total_credits,
        MAX(charge_amt)                                       AS charge_amt,
        MAX(credit_amt)                                       AS credit_amt,
        MAX(TRY_CAST(amount_due_1_normalized AS DECIMAL(18,2))) AS amount_due
    FROM statement_lines
    GROUP BY INVOICE_NO
),
family_agg AS (
    SELECT
        base_invoice_no,
        SUM(charge_amt) AS family_total_charges,
        SUM(credit_amt) AS family_total_credits,
        MAX(TRY_CAST(amount_due_1_normalized AS DECIMAL(18,2))) AS family_amount_due
    FROM statement_lines
    GROUP BY base_invoice_no
),
family_variants AS (
    SELECT base_invoice_no, COUNT(DISTINCT INVOICE_NO) AS variants_on_statement
    FROM statement_lines
    GROUP BY base_invoice_no
),
bill_lookup AS (
    SELECT
        tranid,
        MAX(TRY_CAST(total AS DECIMAL(18,2)))         AS total,
        MAX(CASE WHEN status = 'B' THEN 1 ELSE 0 END) AS is_paid_in_full
    FROM bronze.netsuite_vendorbill
    GROUP BY tranid
),
credit_lookup AS (
    SELECT
        tranid,
        MAX(TRY_CAST(total AS DECIMAL(18,2)))                                     AS total,
        MAX(CASE WHEN TRY_CAST(unapplied AS DECIMAL(18,2)) = 0 THEN 1 ELSE 0 END) AS is_fully_applied
    FROM bronze.netsuite_vendorcredit
    GROUP BY tranid
),
family_netsuite_presence AS (
    SELECT
        sl.base_invoice_no,
        MAX(CASE WHEN bl.tranid IS NOT NULL THEN 1 ELSE 0 END) AS any_bill_exists,
        MAX(CASE WHEN cl.tranid IS NOT NULL THEN 1 ELSE 0 END) AS any_credit_exists
    FROM statement_lines sl
    LEFT JOIN bill_lookup bl ON bl.tranid = sl.INVOICE_NO
    LEFT JOIN credit_lookup cl ON cl.tranid = sl.INVOICE_NO
    GROUP BY sl.base_invoice_no
),
family_has_independent_match AS (
    -- Same exclusion as the standalone Rule 3 query and SUMMARY's classified
    -- CTE: if ANY family member already ties out on its own (Rule 2's
    -- condition), the family's imbalance is self-inflicted and Rule 3
    -- shouldn't claim it.
    SELECT
        i.base_invoice_no,
        MAX(CASE WHEN i.total_charges = i.total_credits
                       AND (bl.is_paid_in_full = 1 OR cl.is_fully_applied = 1)
                  THEN 1 ELSE 0 END) AS has_independent_match
    FROM invoice_shape i
    LEFT JOIN bill_lookup bl ON bl.tranid = i.INVOICE_NO
    LEFT JOIN credit_lookup cl ON cl.tranid = i.INVOICE_NO
    GROUP BY i.base_invoice_no
),
classified AS (
    SELECT
        i.INVOICE_NO,
        i.base_invoice_no,
        CASE
            WHEN fv.variants_on_statement = 1
                 AND bl.is_paid_in_full = 1
                 AND (
                    (i.line_count = 1 AND i.charge_line_count = 1 AND i.credit_line_count = 0 AND i.charge_amt = bl.total)
                    OR (i.line_count = 1 AND i.charge_line_count = 0 AND i.credit_line_count = 1 AND i.credit_amt = bl.total)
                    OR (i.line_count = 2 AND i.charge_line_count = 1 AND i.credit_line_count = 1
                        AND i.charge_amt = i.credit_amt AND i.charge_amt = bl.total)
                 )
                THEN 1   -- RULE_1_DIRECT_MATCH
            WHEN i.total_charges = i.total_credits AND bl.is_paid_in_full = 1
                THEN 2   -- RULE_2_MATCH_BILL
            WHEN i.total_charges = i.total_credits AND cl.is_fully_applied = 1
                THEN 2   -- RULE_2_MATCH_CREDIT
            WHEN fa.family_total_charges IS NOT NULL
                 AND fa.family_total_credits IS NOT NULL
                 AND fa.family_total_charges <> fa.family_total_credits
                 AND fa.family_amount_due IS NOT NULL
                 AND ABS(fa.family_total_charges - fa.family_total_credits - fa.family_amount_due) <= 0.01
                 AND bl_base.is_paid_in_full = 1
                 AND fhim.has_independent_match = 0
                THEN 3   -- RULE_3_AMOUNT_DUE_BALANCED
            WHEN fa.family_total_charges = fa.family_total_credits
                 AND fnp.any_bill_exists = 0
                 AND fnp.any_credit_exists = 0
                THEN 4   -- RULE_4_SELF_CANCEL
            ELSE 5       -- UNRESOLVED_NEEDS_REVIEW
        END AS rule_priority
    FROM invoice_shape i
    JOIN family_variants fv ON fv.base_invoice_no = i.base_invoice_no
    JOIN family_agg fa ON fa.base_invoice_no = i.base_invoice_no
    JOIN family_netsuite_presence fnp ON fnp.base_invoice_no = i.base_invoice_no
    JOIN family_has_independent_match fhim ON fhim.base_invoice_no = i.base_invoice_no
    LEFT JOIN bill_lookup bl ON bl.tranid = i.INVOICE_NO
    LEFT JOIN credit_lookup cl ON cl.tranid = i.INVOICE_NO
    LEFT JOIN bill_lookup bl_base ON bl_base.tranid = i.base_invoice_no
),
family_classified AS (
    -- Collapse to one row per family: the best (lowest-numbered = highest
    -- priority) bucket any member achieved.
    SELECT
        base_invoice_no,
        MIN(rule_priority) AS best_priority
    FROM classified
    GROUP BY base_invoice_no
)
SELECT
    CASE best_priority
        WHEN 1 THEN 'RULE_1_DIRECT_MATCH'
        WHEN 2 THEN 'RULE_2_MATCH'
        WHEN 3 THEN 'RULE_3_AMOUNT_DUE_BALANCED'
        WHEN 4 THEN 'RULE_4_SELF_CANCEL'
        ELSE 'UNRESOLVED_NEEDS_REVIEW'
    END AS rule_bucket,
    COUNT(*) AS family_count
FROM family_classified
GROUP BY best_priority
ORDER BY family_count DESC;
