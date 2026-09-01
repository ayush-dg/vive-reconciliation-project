import type { ExtractionOutcome } from './aiProvider';
import { extractViaLiaAutoGroup, LIA_AUTO_GROUP_SIGNATURES, LIA_AUTO_GROUP_VENDOR_SLUG } from './extractLiaAutoGroup';
import { extractViaKeystone, KEYSTONE_SIGNATURES, KEYSTONE_VENDOR_SLUG } from './extractKeystone';
import { extractViaFredBeans, FRED_BEANS_SIGNATURES, FRED_BEANS_VENDOR_SLUG } from './extractFredBeans';

/**
 * Session 9 (2026-09-01) — table-driven registry of known-vendor
 * deterministic extractors, replacing Task 8.1's single hardcoded
 * Lia-only special case in vendorIdentification.ts now that Session 9 adds
 * more vendors. Each entry is a real, per-vendor Python parser (ported from
 * the reference implementation), checked against the document's own raw
 * text via its real printed signature — not this project's synthetic
 * "VENDOR: <name>" test-fixture marker, which none of these real vendor
 * PDFs ever contain. Adding a vendor here means adding one entry, not a new
 * branch in vendorIdentification.ts's routing logic.
 */

export type KnownVendorExtractor = {
  vendorSlug: string;
  signatures: string[];
  extract: (pdfBytes: Buffer) => Promise<ExtractionOutcome>;
};

export const KNOWN_VENDOR_EXTRACTORS: KnownVendorExtractor[] = [
  { vendorSlug: LIA_AUTO_GROUP_VENDOR_SLUG, signatures: LIA_AUTO_GROUP_SIGNATURES, extract: extractViaLiaAutoGroup },
  { vendorSlug: KEYSTONE_VENDOR_SLUG, signatures: KEYSTONE_SIGNATURES, extract: extractViaKeystone },
  { vendorSlug: FRED_BEANS_VENDOR_SLUG, signatures: FRED_BEANS_SIGNATURES, extract: extractViaFredBeans },
];

/** First entry whose signature appears in the document's raw text, or null
 * if this document doesn't match any known deterministic vendor — falls
 * through to the existing generic guessedSlug/matched/Claude routing
 * unchanged. */
export function findKnownVendorExtractor(pdfText: string): KnownVendorExtractor | null {
  return KNOWN_VENDOR_EXTRACTORS.find((v) => v.signatures.some((sig) => pdfText.includes(sig))) ?? null;
}
