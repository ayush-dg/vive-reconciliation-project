# VIVE Reconciliation -- Azure App Service demo (lightweight)

Provisions the "lightweight demo" resource set discussed for this app:
App Service (Web App for Containers), Azure Container Registry, an Azure
AI Foundry account for Claude, and a Storage account for archival.

Deliberately excludes Azure SQL and the Fabric SQL database item -- the
app's own `src/lakehouse/connection.py` falls back to SQLite for every
table when `AZURE_SQL_SERVER` is unset, which is a real, already-supported
code path, not a workaround. This also avoids the Fabric connection's
`AzureCliCredential` auth, which requires an interactive `az login` session
and does not work inside an App Service container.

This is a standalone demo config, separate from `vive-terraform` and from
any future production Fabric/Azure IaC tracked in `docs/ARCHITECTURE.md`.

## What Terraform does NOT do

**Deploying the Claude Haiku 4.5 / Claude Sonnet 4.6 model deployments
inside the Azure AI Foundry resource is a manual step**, done in the
Foundry portal after `terraform apply`. Reasons:

- Anthropic models on Azure AI Foundry are offered through the Azure
  Marketplace, which requires accepting marketplace/legal terms
  interactively in the portal the first time in a subscription --
  this isn't something `terraform apply` can click through for you.
- Region availability for Anthropic models is limited and changes over
  time -- verify the resource group's actual region supports them
  (there's no separate `location` variable here; every resource inherits
  its region from the resource group you point at):
  `az group show -n <resource_group_name> --query location`

Terraform creates the Foundry *account* (which is what gives you the
endpoint and API key) and wires its output into the web app's app
settings. You add the two model deployments on top of it.

## Steps

1. **Fill in variables.**
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   # edit terraform.tfvars: subscription_id (az account list -o table),
   # resource_group_name (must already exist and be empty),
   # web_session_secret (openssl rand -hex 32)
   ```

2. **Provision infrastructure.**
   ```bash
   terraform init
   terraform apply
   ```

   On a first-ever apply, this fails with `expected
   "site_config.0.application_stack.0.docker_registry_username" to not be
   an empty string`. That's because Terraform evaluates every resource's
   expressions during planning (not just the ones actually changing), and
   the ACR's `admin_username`/`admin_password` only exist once
   `admin_enabled` is genuinely `true` on the real resource --
   `-target=azurerm_container_registry.acr` does NOT dodge this, since
   targeting only limits what gets *applied*, not what gets *evaluated*
   during planning. Fix it by flipping the flag directly via CLI first, so
   the credentials already exist as real values before Terraform ever
   reads them:
   ```bash
   az acr create -n <acr-name-from-the-failed-plan> -g <resource_group_name> --sku Basic
   az acr update -n <acr-name-from-the-failed-plan> -g <resource_group_name> --admin-enabled true
   terraform apply
   ```
   (If the registry was already created by the failed apply, skip the
   `az acr create` line -- `az acr update` alone is enough.) After this,
   `terraform apply` should complete in one pass on every run after.

   Note the outputs: `acr_login_server`, `webapp_name`, `webapp_url`,
   `foundry_account_name`.

3. **Add the Claude model deployments (manual, portal).**
   - Go to the Azure AI Foundry portal, open the account Terraform created
     (`foundry_account_name` output).
   - Accept the Anthropic marketplace offer if prompted.
   - Create two deployments:
     - `claude-haiku-4-5` -> model `claude-haiku-4-5-20251001`
     - `claude-sonnet-4-6` -> model `claude-sonnet-4-6`
   - These names must match `claude_haiku_deployment_name` /
     `claude_sonnet_deployment_name` in variables.tf (defaults already
     match -- only change one side if you rename a deployment).
   - If the portal gives you a different Anthropic-compatible endpoint path
     than `<foundry_endpoint>anthropic`, update the web app's
     `AZURE_CLAUDE_ENDPOINT` app setting to match (`az webapp config
     appsettings set`), then restart the app.

4. **Build and push the image.**
   ```bash
   ACR=$(terraform output -raw acr_login_server)
   az acr build --registry $(terraform output -raw acr_name) \
     --image vive-reconciliation:latest ../..
   ```
   (Run from this directory; `../..` points at the repo root where the
   Dockerfile lives.)

5. **Restart the web app** so it pulls the freshly-pushed image.
   ```bash
   az webapp restart -g <resource_group_name> -n $(terraform output -raw webapp_name)
   ```

6. **Smoke test.** Open `terraform output -raw webapp_url`, log in, and
   upload a sample PDF from `sample_data/` through the manual upload flow
   (not the Event Grid drop-zone -- that's intentionally out of scope for
   this lightweight demo). Confirm it extracts, matches, and shows up on
   the dashboard.

## Where the database lives

There's no separate database resource in this demo -- `AZURE_SQL_SERVER`
is left unset, so `src/lakehouse/connection.py` falls back to SQLite for
every table (Bronze/Silver/Gold and all Recon tables). The file lives at
`/app/lakehouse/reconciliation.db` inside the container (a path relative
to `connection.py` itself, resolved against the Dockerfile's `WORKDIR
/app`).

That path is NOT covered by App Service's `/home` persistence -- it's
part of the container's own writable layer, so on its own it would be
wiped on every restart, redeploy, or scale event. This config mounts an
Azure Files share directly at `/app/lakehouse` (the `azurerm_storage_share
"lakehouse"` resource + the web app's `storage_account` block in
`main.tf`) so the app's existing SQLite writes land on durable storage
with no code change.

This still assumes a single instance -- don't turn on autoscale. SQLite
doesn't handle concurrent writers across multiple instances safely, and
nothing in this config partitions the file per instance.

## Tearing down

```bash
terraform destroy
```
This removes everything Terraform created. It does not touch the resource
group itself (Terraform only references it via a data source, never
creates or destroys it).
