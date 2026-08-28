// Task 3.2 test cases — arithmetic and structural validation gate (G2, amended).
import { validateExtraction } from '../src/lib/validationGate.ts';

let failures = 0;
function check(label, condition) {
  if (condition) {
    console.log(`PASS: ${label}`);
  } else {
    console.error(`FAIL: ${label}`);
    failures++;
  }
}

function statement(overrides) {
  return {
    vendorNameGuess: 'Test Vendor',
    statementPeriod: '2026-07',
    statementTotal: 100,
    lines: [{ invoiceRef: 'INV-1', roNumber: null, amount: 100, date: '2026-07-01' }],
    ...overrides,
  };
}

// --- TC-1: lines sum correctly, valid dates/amounts -> eligible regardless of confidence ---
{
  const result = validateExtraction(statement({}));
  check('TC-1: correct sum, valid fields -> status pass', result.status === 'pass');
  check('TC-1: no reason codes on pass', result.reasonCodes.length === 0);
}

// --- TC-2: lines sum incorrectly -> not eligible, triggers retry path ---
{
  const result = validateExtraction(
    statement({ statementTotal: 999, lines: [{ invoiceRef: 'INV-2', roNumber: null, amount: 100, date: '2026-07-01' }] })
  );
  check('TC-2: incorrect sum -> status fail', result.status === 'fail');
  check('TC-2: reason includes ARITHMETIC_MISMATCH', result.reasonCodes.includes('ARITHMETIC_MISMATCH'));
  check('TC-2: requiresReview true on fail', result.requiresReview === true);
}

// --- TC-3: line missing invoice_number, no ro_number fallback -> not eligible ---
{
  const result = validateExtraction(
    statement({ lines: [{ invoiceRef: null, roNumber: null, amount: 100, date: '2026-07-01' }] })
  );
  check('TC-3: missing invoice_ref/ro_number -> status fail', result.status === 'fail');
  check('TC-3: reason includes MISSING_IDENTIFIER', result.reasonCodes.includes('MISSING_IDENTIFIER'));
}

// --- TC-4: low-confidence but structurally/arithmetically valid -> proceeds to Silver ---
// (Confidence isn't a validateExtraction input at all — G2 amended removed it from this
// gate entirely; this case confirms a correct statement passes with no reference to
// confidence, i.e. there is no code path here that could even consult it.)
{
  const result = validateExtraction(statement({}));
  check('TC-4: structurally/arithmetically valid statement passes (confidence not a gate input)', result.status === 'pass');
}

// --- TC-5: blank-amount (credit/payment) line, valid invoice_number -> reaches Silver ---
{
  const result = validateExtraction(
    statement({
      statementTotal: 100,
      lines: [
        { invoiceRef: 'INV-5', roNumber: null, amount: 100, date: '2026-07-01' },
        { invoiceRef: 'CREDIT-1', roNumber: null, amount: null, date: '2026-07-02' },
      ],
    })
  );
  check('TC-5: blank-amount credit line with valid invoice_ref -> status pass', result.status === 'pass');
}

// --- TC-6: no extraction at all (extraction error upstream) -> fail, requires review ---
{
  const result = validateExtraction(null);
  check('TC-6: null extraction -> status fail', result.status === 'fail');
  check('TC-6: reason includes EXTRACTION_ERROR', result.reasonCodes.includes('EXTRACTION_ERROR'));
}

// --- TC-7 (Task 3.1 Finding 2 regression): structurally/arithmetically valid lines but no
// identifiable vendor name -> must fail structurally, not silently pass. Without this, a
// document could show arithmetic_pass=1/structural_pass=1 forever while never reaching
// Silver (vendor identification never resolving downstream in extractionPipeline.ts). ---
{
  const result = validateExtraction(statement({ vendorNameGuess: null }));
  check('TC-7: no vendor name guess -> status fail', result.status === 'fail');
  check('TC-7: reason includes MISSING_IDENTIFIER for missing vendor name', result.reasonCodes.includes('MISSING_IDENTIFIER'));
  check('TC-7: evidence flags vendorNameGuessMissing', result.evidence.vendorNameGuessMissing === true);
}

// --- TC-8: date does not parse -> structural failure ---
{
  const result = validateExtraction(
    statement({ lines: [{ invoiceRef: 'INV-8', roNumber: null, amount: 100, date: 'not-a-date' }] })
  );
  check('TC-8: unparseable date -> status fail', result.status === 'fail');
  check('TC-8: reason includes MISSING_IDENTIFIER for unparseable date', result.reasonCodes.includes('MISSING_IDENTIFIER'));
}

// --- TC-9 (challenge-review regression): a NaN statement_total (e.g. a
// garbled "TOTAL: xyz" capture coerced via Number()) must not silently pass —
// NaN !== null and NaN > tolerance is always false, so this was a live
// arithmetic-gate bypass before the fix. ---
{
  const result = validateExtraction(statement({ statementTotal: Number('xyz') }));
  check('TC-9: NaN statement_total -> status fail', result.status === 'fail');
  check('TC-9: reason includes ARITHMETIC_MISMATCH for NaN total', result.reasonCodes.includes('ARITHMETIC_MISMATCH'));
}

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 3.2 test cases PASS.');
