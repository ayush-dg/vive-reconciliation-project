# Mailbox Logic Apps (instant intake)

When an email lands in the statements mailbox, Microsoft Graph notifies
`<prefix>-notify` within seconds. It writes the email's PDF attachments to
the mailbox container, in the same blob path format as the mailbox-sync
Function (`mailbox/{yyyy}/{mm}/{dd}/raw_statement/{uuid}__{name}_{timestamp}.pdf`),
then POSTs the web app's `/mailbox-sync/auto` so they're queued at once.

`<prefix>-subscription` runs every 12 hours. It creates the Graph
subscription, or pushes its expiry 3 days out (Graph's limit for mail is
about 7 days). So a missed renewal or two is harmless.

The Function's 30-minute timer is untouched and stays the backstop. If both
pick up the same email, the second copy is byte-identical, and intake marks
it a duplicate before any extraction.

## What it needs

- The Function's app registration (`graph_client_id`), with Graph
  **Mail.Read (application)**. It already has that.
- A container SAS (create + write only), made by Terraform from the storage
  account key; a re-apply after 180 days rotates it (see `upload_sas_expiry`).

## Deploy (one state per environment)

```
cd deploy/mailbox-logic-app
terraform workspace select -or-create dev    # or prod
# terraform.tfvars (gitignored): the values for that environment; see variables.tf
terraform init
terraform apply
```

The subscription Logic App's first run starts as soon as it's created, and
registers the Graph subscription.

For prod, use a separate workspace and a separate tfvars file
(`terraform apply -var-file=prod.tfvars`) with:
- `rg-vive-if`;
- the prod Function's storage account and settings;
- `https://vivecollision-reconciliation.azurewebsites.net/mailbox-sync/auto`;
- a different `name_prefix`.

## Turning it off

- **Disable both Logic Apps** in the portal
  (`az logic workflow update --state Disabled`). The Graph subscription
  then expires on its own within 3 days. Until then Graph's calls fail and
  are dropped.
- **Or remove everything:** `terraform destroy`.

## Checking it

Logic App → Runs history. A run with the `Acknowledge` branch is a real
notification. A run with `Return_validation_token` is Graph checking the URL.
