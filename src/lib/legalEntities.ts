/**
 * Legal entity options for the Upload screen's dropdown (Task 2.1). No
 * canonical list exists anywhere in the signed-off docs — UI_SURFACE.md
 * itself flags this field's provenance as a genuinely open gap ("Legal
 * Entity field: user-selected, or inferred? Real architectural gap"), and
 * Task 2.1's own description says to flag this for revisiting, not resolve
 * it. Values below are a placeholder set only, not sourced from VIVE's real
 * legal entity structure.
 */
export const LEGAL_ENTITIES = [
  { id: 'vive-holdings', name: 'Vive Collision Holdings, LLC' },
  { id: 'vive-mid-atlantic', name: 'Vive Collision — Mid-Atlantic Region' },
  { id: 'vive-northeast', name: 'Vive Collision — Northeast Region' },
] as const;
