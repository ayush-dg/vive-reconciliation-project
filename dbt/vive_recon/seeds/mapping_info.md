

## 1. Suppose Bronze contains:

```json
{
  "Invoice #": "INV-123",
  "Remaining Amount": "450.50",
  "Reference #": "PO-55"
}
```

The mapping sheet contains:

| vendor_id | raw_field_name   | canonical_field_name    | target_type |
| --------- | ---------------- | ------------------------ | ----------- |
| keystone  | Invoice #        | original_invoice_number | string      |
| keystone  | Remaining Amount | amount_remaining        | decimal     |
| keystone  | Reference #      | invoice_number_ref      | string      |

dbt can therefore transform:

```text
Bronze                         Silver
------                         ------
Invoice #        ───────────→  original_invoice_number
Remaining Amount ───────────→  amount_remaining
Reference #      ───────────→  invoice_number_ref
```

---

## 2. How dbt uses it

The transformation is:

```text
Bronze
  │
  │ raw_payload = JSON array
  ▼
Explode array
  │
  │ one extracted line
  ▼
Explode JSON object
  │
  │ raw_field_name + value
  ▼
JOIN mapping sheet
  │
  │ vendor_id + raw_field_name
  ▼
Get canonical_field_name
  │
  ▼
Build canonical Silver row
  │
  ▼
silver.statement_line
```

So the SQL model is **generic**.

It doesn't need:

```text
if vendor = Keystone...
if vendor = ASTECH...
if vendor = NUCAR...
```

The mapping table contains that vendor-specific knowledge.

---

## 3. What happens to unmapped fields?

Some vendor fields don't have a corresponding canonical Silver column.

For those, we explicitly have:

```text
canonical_field_name = NULL
target_type = NULL
```

For example:

| vendor_id | raw_field_name  | canonical_field_name | target_type |
| --------- | --------------- | -------------------- | ----------- |
| keystone  | balance_forward | NULL                 | NULL        |

This means:

> We know this field exists, but we don't want it as a standard Silver column.

Instead, dbt can preserve it inside:

```text
silver_extra_attributes
```

So we don't lose vendor-specific information.

---

## 4. Why use the existing Silver field names?

We're intentionally mapping into the **existing live Silver schema**.

For example:

```text
raw vendor field
      ↓
"Remaining Amount"
      ↓
amount_remaining
```

rather than introducing a new name like:

```text
outstanding_amount
```

This keeps the new mapping-driven model compatible with the existing production Silver model and makes comparison between the two much easier.

---

## 5. Why do we need `mapping_config_version`?

Mappings can change.

For example:

**v1**

```text
"Remaining Amount" → amount_remaining
```

Later, the vendor introduces:

```text
"Balance Due"
```

We can update the configuration to:

**v2**

```text
"Remaining Amount" → amount_remaining
"Balance Due"      → amount_remaining
```

Silver can record the mapping version used for each row.

That gives us lineage:

```text
Silver row
    ↓
mapping_config_version = v1
    ↓
exact mapping rules that produced this row
```

---

## 6. What does this change for onboarding a vendor?

### Before

Adding a vendor could require:

```text
New vendor
   ↓
Modify Python extraction/mapping logic
   ↓
Modify Bronze/Silver logic
   ↓
Test code
   ↓
Deploy
```

### With the mapping configuration

```text
New vendor
   ↓
Add mapping rows
   ↓
dbt seed
   ↓
dbt run
   ↓
Same generic Silver model
```

The **transformation logic stays the same**; only the configuration changes.

---

The clean separation is:

```text
Extraction
    ↓
Preserve vendor's raw fields
    ↓
Bronze
    ↓
Mapping configuration
    ↓
Generic dbt transformation
    ↓
Canonical Silver
```

**Code tells dbt HOW to transform.**

**The mapping sheet tells dbt WHAT each vendor field means.**

That's the main purpose of the mapping sheet.
