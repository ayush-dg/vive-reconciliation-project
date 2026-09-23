# VIVE Reconciliation -- Azure prod (App Service + Azure SQL)

Provisions the Azure-side resources for a prod deployment of the VIVE
Reconciliation app: Linux Web App for Containers, its own Container
Registry, a real Azure SQL Database, an archival Storage account, and a
mailbox-sync Function App (Flex Consumption) with its own storage account
modeled on the existing `viveinsightstatements`. Targets the existing
`rg-vive-if` resource group.

Standalone from `deploy/azure-app-service-demo/` (that one is the
lightweight dev/demo variant, kept as-is, not reused here).

## What this deliberately does NOT do

- **No Fabric resources.** The Fabric workspace, Lakehouse, Warehouse, and
  SQL-database-in-Fabric item are created by hand, separately -- Terraform
  can't manage Fabric items via the `azurerm` provider at all. Once those
  prod Fabric items exist, fill in the `fabric_*` variables in
  `terraform.tfvars` (see `terraform.tfvars.example`) and `terraform
  apply` again -- that only updates the web app's app settings, it doesn't
  touch Fabric. Until then, those app settings are left empty, which is a
  real, already-supported "not configured" state in
  `src/lakehouse/connection.py` (`_using_fabric_sqldb()`) and
  `src/lakehouse/fabric_sql.py` (`_fabric_configured()`) -- the 3
  Fabric-cutover Recon tables (`extraction_cache`, `document_intake_log`,
  `validation_document_review_queue`) just live in Azure SQL like every
  other table until then.
- **No new Azure AI Foundry / Cognitive Services account.** The existing
  Claude API key and endpoint are passed in as variables (`claude_api_key`,
  `claude_endpoint`) instead.
- **No dropzone/Event-Grid auto-intake storage.** Only the main archival
  storage account + `vendor-statements` container are provisioned. Manual
  upload works without it; add a second storage account +
  `incoming-statements` container later if auto-intake is needed in prod.
- **No Graph app registration for mailbox-sync.** The Function App is
  provisioned, but the Entra ID app registration that grants it
  `Mail.Read` on the target mailbox is not -- that needs the `azuread`
  provider (or the portal) and admin consent, neither of which Terraform
  does here. Supply an existing or new registration's credentials via
  `mailbox_graph_tenant_id`/`mailbox_graph_client_id`/`mailbox_graph_client_secret`.

## Steps

1. **Fill in variables.**
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   # edit terraform.tfvars: subscription_id, sql_admin_client_ip,
   # claude_api_key, claude_endpoint, mailbox_graph_tenant_id,
   # mailbox_graph_client_id, mailbox_graph_client_secret,
   # mailbox_target_mailbox
   ```

2. **Provision infrastructure.**
   ```bash
   terraform init
   terraform apply
   ```
   Same first-apply ACR quirk as the demo config may show up here too:
   if it fails with `expected
   "site_config.0.application_stack.0.docker_registry_username" to not be
   an empty string`, fix it by flipping the flag directly via CLI before
   re-applying:
   ```bash
   az acr update -n <acr-name-from-the-failed-plan> -g rg-vive-if --admin-enabled true
   terraform apply
   ```

   Note the outputs: `acr_login_server`, `acr_name`, `webapp_name`,
   `webapp_url`, `sql_server_fqdn`, `sql_database_name`.

3. **Build and push the image.**
   ```bash
   az acr build --registry $(terraform output -raw acr_name) \
     --image vive-reconciliation:latest ../..
   ```
   (Run from this directory; `../..` points at the repo root where the
   Dockerfile lives. Use `az acr build`, not local Docker -- local Docker
   Desktop has been unreliable for this app.)

4. **Restart the web app** so it pulls the freshly-pushed image.
   ```bash
   az webapp restart -g rg-vive-if -n $(terraform output -raw webapp_name)
   ```
   (Only immediately after a fresh image push -- don't restart during an
   in-progress `az acr build`/pull, it can interrupt the pull and cause an
   outage. Poll HTTP status to confirm instead of restarting speculatively.)

5. **Smoke test.** Open `terraform output -raw webapp_url`, log in
   (`scripts/create_admin.py` against the new Azure SQL database if no
   user exists yet), and upload a sample PDF through the manual upload
   flow. Confirm it extracts, matches, and shows up on the dashboard.

## Where the database lives

`AZURE_SQL_SERVER` is always set here, so `src/lakehouse/connection.py`
uses the real Azure SQL Database for every table (Bronze/Silver/Gold +
all Recon tables not yet cut over to Fabric), not the SQLite fallback --
this differs from the dev/demo config, which leaves `AZURE_SQL_SERVER`
unset.

## Tearing down

```bash
terraform destroy
```
Removes everything this config created. It does not touch the resource
group itself (referenced via a data source, never created/destroyed by
Terraform) or anything else already in `rg-vive-if`.
