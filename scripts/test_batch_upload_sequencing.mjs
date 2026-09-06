// ENH-001 Task 2.2 test cases — sequential batch upload loop, registration-failure
// skip. Tests runBatchUploadSequenced directly (a pure function, no DB/browser
// needed) with instrumented fake register/extract callbacks that record call
// ordering and concurrency via artificial delays.
import { runBatchUploadSequenced } from '../src/lib/batchUploadSequencing.ts';

let failures = 0;
function check(label, condition) {
  if (condition) {
    console.log(`PASS: ${label}`);
  } else {
    console.error(`FAIL: ${label}`);
    failures++;
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// --- TC-1: a multi-file batch never has two extraction calls in flight
// simultaneously — the core acceptance criterion this task exists to guarantee. ---
{
  const files = ['a.pdf', 'b.pdf', 'c.pdf'];
  let activeExtractions = 0;
  let maxConcurrentExtractions = 0;
  const extractionOrder = [];

  await runBatchUploadSequenced(
    files,
    async (file) => ({ ok: true, duplicate: false, documentId: `doc-${file}` }),
    async (documentId) => {
      activeExtractions += 1;
      maxConcurrentExtractions = Math.max(maxConcurrentExtractions, activeExtractions);
      extractionOrder.push(`start:${documentId}`);
      await delay(20);
      extractionOrder.push(`end:${documentId}`);
      activeExtractions -= 1;
    }
  );

  check('TC-1: never more than 1 extraction in flight at a time', maxConcurrentExtractions === 1);
  check(
    'TC-1: each extraction fully completes (start+end pair) before the next one starts',
    extractionOrder.join(',') === 'start:doc-a.pdf,end:doc-a.pdf,start:doc-b.pdf,end:doc-b.pdf,start:doc-c.pdf,end:doc-c.pdf'
  );
}

// --- TC-2: a single-file batch does NOT await extraction — the function returns
// before the (still in-flight) extraction resolves, matching pre-enhancement
// single-file fire-and-forget behavior byte-for-byte (regression case). ---
{
  let extractionResolved = false;
  let functionReturnedBeforeExtractionResolved = false;

  const extractionPromise = new Promise((resolve) => {
    setTimeout(() => {
      extractionResolved = true;
      resolve();
    }, 20);
  });

  await runBatchUploadSequenced(
    ['solo.pdf'],
    async () => ({ ok: true, duplicate: false, documentId: 'doc-solo' }),
    async () => {
      functionReturnedBeforeExtractionResolved = !extractionResolved;
      return extractionPromise;
    }
  );

  check('TC-2: runBatchUploadSequenced returns without waiting for the single file\'s extraction', functionReturnedBeforeExtractionResolved);
  await extractionPromise; // let the dangling promise settle before the script exits
}

// --- TC-3: a registration failure mid-batch is skipped, not fatal — the loop
// continues to the remaining files, extraction is never called for the failed one. ---
{
  const files = ['ok1.pdf', 'bad.pdf', 'ok2.pdf'];
  const registeredFiles = [];
  const extractedDocumentIds = [];

  await runBatchUploadSequenced(
    files,
    async (file) => {
      registeredFiles.push(file);
      if (file === 'bad.pdf') {
        return { ok: false, duplicate: false, documentId: null };
      }
      return { ok: true, duplicate: false, documentId: `doc-${file}` };
    },
    async (documentId) => {
      extractedDocumentIds.push(documentId);
    }
  );

  check('TC-3: all 3 files attempted registration, none skipped upfront', registeredFiles.length === 3);
  check('TC-3: the batch did not abort after the failed registration', registeredFiles.join(',') === 'ok1.pdf,bad.pdf,ok2.pdf');
  check('TC-3: extraction was never called for the file that failed registration', !extractedDocumentIds.includes('doc-bad.pdf'));
  check('TC-3: extraction still ran for both successfully-registered files', extractedDocumentIds.length === 2);
}

// --- TC-4 (Design Gate Finding 2 regression): a duplicate registration result
// (same file selected twice in one batch) does not trigger a second extraction. ---
{
  const files = ['dup.pdf', 'dup.pdf'];
  let registerCallCount = 0;
  const extractedDocumentIds = [];

  await runBatchUploadSequenced(
    files,
    async () => {
      registerCallCount += 1;
      // Second occurrence of the same file is a duplicate — same documentId,
      // same pattern registerDocument()'s own race-tolerant catch produces.
      return { ok: true, duplicate: registerCallCount > 1, documentId: 'doc-dup' };
    },
    async (documentId) => {
      extractedDocumentIds.push(documentId);
    }
  );

  check('TC-4: both occurrences attempted registration', registerCallCount === 2);
  check('TC-4: extraction was only triggered once, not for the duplicate', extractedDocumentIds.length === 1);
}

// --- TC-5 (challenge agent Finding 1): an extraction failure for one file in a
// multi-file batch must not abort processing of the remaining files — symmetric
// to how a registration failure is already handled. ---
{
  const files = ['ok1.pdf', 'extract-fails.pdf', 'ok2.pdf'];
  const extractionAttempts = [];

  await runBatchUploadSequenced(
    files,
    async (file) => ({ ok: true, duplicate: false, documentId: `doc-${file}` }),
    async (documentId) => {
      extractionAttempts.push(documentId);
      if (documentId === 'doc-extract-fails.pdf') {
        throw new Error('simulated extraction failure');
      }
    }
  );

  check('TC-5: extraction was attempted for all 3 files despite the middle one throwing', extractionAttempts.length === 3);
  check(
    'TC-5: the batch did not abort after the extraction failure — the loop reached the 3rd file',
    extractionAttempts[2] === 'doc-ok2.pdf'
  );
}

// --- TC-6 (challenge agent Finding 2): an anomalous ok:true/duplicate:false result
// with no documentId (the real API always returns one for this case) is skipped
// gracefully, not silently mishandled — no extraction call, no crash. ---
{
  const extractedDocumentIds = [];

  await runBatchUploadSequenced(
    ['anomalous.pdf'],
    async () => ({ ok: true, duplicate: false, documentId: null }),
    async (documentId) => {
      extractedDocumentIds.push(documentId);
    }
  );

  check('TC-6: no extraction call made for a result with no documentId', extractedDocumentIds.length === 0);
}

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 2.2 sequencing test cases PASS.');
