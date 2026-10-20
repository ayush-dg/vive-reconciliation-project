# Prod Azure resources only -- App Service, Azure SQL, ACR, and archival
# blob storage. Deliberately excludes any Fabric item (Lakehouse,
# Warehouse, SQL database in Fabric) -- those are provisioned by hand
# separately, per explicit instruction. The FABRIC_* variables below exist
# only so this config can pass their values through to the web app's app
# settings once those items exist; Terraform never creates or manages them.
#
# Also excludes an Azure AI Foundry / Cognitive Services account -- the
# existing Claude API key/endpoint (already used elsewhere) is passed in
# directly instead of provisioning a new one.

variable "subscription_id" {
  description = "Azure subscription ID to deploy into. Check with: az account list -o table"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the existing resource group to deploy into. All resources inherit region from the per-resource location variables below, not from this resource group's own location."
  type        = string
  default     = "rg-vive-if"
}

variable "name_prefix" {
  description = "Prefix for resource names that allow hyphens (SQL server, App Service Plan, etc). Globally-unique alphanumeric-only resources (ACR, storage account) derive their own prefix from this by stripping hyphens -- see locals.tf."
  type        = string
  default     = "vivecollision-prod"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.name_prefix))
    error_message = "name_prefix must be lowercase letters, digits, and hyphens only."
  }
}

variable "app_service_name" {
  description = "Exact name of the Linux Web App. Must be globally unique across Azure (becomes <name>.azurewebsites.net)."
  type        = string
  default     = "vivecollision-reconciliation"
}

variable "app_service_sku" {
  description = "App Service Plan SKU. B1 (Basic) -- matches the existing vivecollision-plan in this subscription/region, already proven to work here."
  type        = string
  default     = "B1"
}

variable "skip_fabric_visibility_wait" {
  description = "TEMPORARY (2026-09-23): when true, sets SKIP_FABRIC_VISIBILITY_WAIT=true so src/lakehouse/bronze_unnest.py's wait_for_visibility() short-circuits -- faster extraction, but reintroduces the read-after-write race that function exists to guard against (a dbt run right after a Bronze write can silently see 0 rows). Flip back to false to restore the real wait."
  type        = bool
  default     = false
}

variable "admin_email" {
  description = "Email for the first admin login (scripts/create_admin.py). Passed through to the web app's own app settings (ADMIN_EMAIL) so the credential lives in Azure config, not hardcoded in git -- see that script's 2026-09-24 fix note. Not read by the running app itself at request time, only by create_admin.py when run manually (locally, or via az webapp ssh/Kudu exec against this App Service, which picks these up automatically from the container's own environment)."
  type        = string
  default     = ""
}

variable "admin_password" {
  description = "Password for the first admin login (scripts/create_admin.py) -- see admin_email's description for the same rationale/usage."
  type        = string
  sensitive   = true
  default     = ""
}

variable "app_service_location" {
  description = "Region for the App Service Plan and Web App. West US 2, matching vivecollision-plan."
  type        = string
  default     = "westus2"
}

variable "sql_location" {
  description = "Region for the Azure SQL Server. West US 2 -- this subscription returns ProvisioningDisabled for Azure SQL in East US/East US 2; West US 2 is proven working (viverecondemo-sql)."
  type        = string
  default     = "westus2"
}

variable "mailbox_storage_location" {
  description = "Region for the mailbox-sync storage account (AzureWebJobsStorage + deployment package container + 'raw' target container). West US, matching the existing viveinsightstatements account and the vive-mailbox-sync Function App itself."
  type        = string
  default     = "westus"
}

variable "function_plan_location" {
  description = "Region for the Flex Consumption plan backing the mailbox-sync Function App. West US, matching the existing ASP-rgviverecon-f57c plan (FC1 SKU)."
  type        = string
  default     = "westus"
}

variable "docker_image_tag" {
  description = "Tag of the vive-reconciliation image in ACR to deploy. Ignored if docker_image_digest is set."
  type        = string
  default     = "latest"
}

variable "docker_image_digest" {
  description = "Optional specific image digest (e.g. \"sha256:b17c7314...\", from `az acr repository show-manifests`) to pin the deployed image to, instead of the mutable docker_image_tag. Takes precedence over docker_image_tag when non-empty. Exists so a rollback (or any pin to a known-good build) is a tracked Terraform change, not an out-of-band `az webapp config container set` that the next unrelated apply would silently revert -- confirmed real 2026-09-24: an admin-credential app_settings change alone reverted a manual image rollback back to :latest, since Terraform treats the whole app_settings/site_config as one unit. Clear back to \"\" to resume tracking docker_image_tag (normally \"latest\")."
  type        = string
  default     = ""
}

variable "sql_admin_client_ip" {
  description = "Your public IPv4 address, so scripts run from your machine (not from inside Azure) can reach the new Azure SQL Database directly. Find it with: curl ifconfig.me"
  type        = string
}

# --- Claude / Anthropic (existing key reused, no new Foundry account) ---

variable "claude_api_key" {
  description = "Existing Azure AI Foundry Claude API key (AZURE_CLAUDE_API_KEY) -- reused as-is, no new Cognitive Services account provisioned for prod."
  type        = string
  sensitive   = true
}

variable "claude_endpoint" {
  description = "Existing Claude endpoint (AZURE_CLAUDE_ENDPOINT), e.g. https://<foundry-account>.services.ai.azure.com/anthropic"
  type        = string
}

variable "claude_sonnet_deployment_name" {
  description = "Deployment name for Claude Sonnet 4.6 (AZURE_CLAUDE_SONNET_DEPLOYMENT) -- primary extraction model."
  type        = string
  default     = "claude-sonnet-4-6"
}

variable "claude_haiku_deployment_name" {
  description = "Deployment name for Claude Haiku 4.5 (AZURE_CLAUDE_DEPLOYMENT) -- exception/--explain narrative only."
  type        = string
  default     = "claude-haiku-4-5"
}

# --- Fabric passthrough (values only -- no Fabric resource is created here) ---
# Leave these at their default ("") until the prod Fabric workspace,
# Lakehouse, Warehouse, and SQL-database-in-Fabric item are created by hand.
# Empty string is a real, already-supported code path: connection.py's
# _using_fabric_sqldb() / fabric_sql.py's _fabric_configured() both treat an
# unset/empty value as "not configured" and fall back to Azure SQL /
# SQLite for the 3 Fabric-cutover Recon tables. Fill these in and re-apply
# once the Fabric items exist.

variable "fabric_tenant_id" {
  type    = string
  default = ""
}

variable "fabric_client_id" {
  type    = string
  default = ""
}

variable "fabric_client_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "fabric_workspace_id" {
  type    = string
  default = ""
}

variable "fabric_lakehouse_name" {
  type    = string
  default = ""
}

variable "fabric_lakehouse_id" {
  type    = string
  default = ""
}

variable "fabric_warehouse_name" {
  type    = string
  default = ""
}

variable "fabric_sql_endpoint" {
  type    = string
  default = ""
}

variable "fabric_sql_endpoint_id" {
  type    = string
  default = ""
}

variable "fabric_sqldb_endpoint" {
  type    = string
  default = ""
}

variable "fabric_sqldb_name" {
  type    = string
  default = ""
}

# --- Mailbox sync (azure-functions/mailbox-sync/) ---
# Graph app registration used for app-only Outlook mail access (MSAL
# client-credentials flow in function_app.py). This is a DIFFERENT
# identity than the fabric_client_id/secret above -- reuses whatever
# Graph app registration already grants Mail.Read on TARGET_MAILBOX, or a
# new one you create for prod. Terraform does not create this
# registration (would need the azuread provider, out of scope here).

variable "mailbox_graph_tenant_id" {
  description = "AZURE_TENANT_ID for the mailbox-sync function's Graph app registration."
  type        = string
}

variable "mailbox_graph_client_id" {
  description = "AZURE_CLIENT_ID for the mailbox-sync function's Graph app registration."
  type        = string
}

variable "mailbox_graph_client_secret" {
  description = "AZURE_CLIENT_SECRET for the mailbox-sync function's Graph app registration."
  type        = string
  sensitive   = true
}

variable "mailbox_target_mailbox" {
  description = "TARGET_MAILBOX -- the Outlook mailbox address mailbox-sync pulls PDF attachments from."
  type        = string
}

variable "mailbox_container_name" {
  description = "MAILBOX_CONTAINER -- blob container mailbox-sync writes PDFs into. Matches the existing 'raw' container on viveinsightstatements."
  type        = string
  default     = "raw"
}

variable "mailbox_watermark_blob_path" {
  description = "WATERMARK_BLOB_PATH -- idempotency watermark blob path within mailbox_container_name."
  type        = string
  default     = "watermark/mailbox.json"
}

variable "mailbox_auto_sync_enabled" {
  description = "AUTO_SYNC_ENABLED on the mailbox Function: its 30-minute timer. Off since 2026-10-20 -- the mailbox Logic Apps take mail as it lands; on as well, every email comes in twice (the second as a duplicate)."
  type        = bool
  default     = false
}

variable "mailbox_autosync_secret" {
  description = "MAILBOX_AUTOSYNC_SECRET, shared by the web app and the mailbox Function (and the Logic Apps' x-vive-autosync-secret header)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "archive_container_name" {
  description = "Container in the mailbox storage account that holds archived statement PDFs."
  type        = string
  default     = "vendor-statements"
}

# --- NetSuite write-back (sandbox) ---

variable "netsuite_writeback_enabled" {
  description = "NETSUITE_WRITEBACK_ENABLED: write reconciliation results and Accept-as-match to the NetSuite sandbox."
  type        = bool
  default     = false
}

variable "netsuite_writeback_pdf_link" {
  description = "NETSUITE_WRITEBACK_PDF_LINK: put the statement's SharePoint link on the bills (needs the SharePoint archive)."
  type        = bool
  default     = false
}

variable "sandbox_account_id" {
  description = "SANDBOX_ACCOUNT_ID, e.g. 7321761_SB1."
  type        = string
  default     = ""
}

variable "sandbox_consumer_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "sandbox_consumer_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "sandbox_token_id" {
  type      = string
  sensitive = true
  default   = ""
}

variable "sandbox_token_secret" {
  type      = string
  sensitive = true
  default   = ""
}

# --- SharePoint statement archive ---

variable "sharepoint_archive_enabled" {
  description = "SHAREPOINT_ARCHIVE_ENABLED: archive RECONCILIATION statements to SharePoint at intake."
  type        = bool
  default     = false
}

variable "sharepoint_tenant_id" {
  type    = string
  default = ""
}

variable "sharepoint_client_id" {
  type    = string
  default = ""
}

variable "sharepoint_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "sharepoint_site_hostname" {
  type    = string
  default = ""
}

variable "sharepoint_site_path" {
  type    = string
  default = ""
}

variable "sharepoint_library" {
  type    = string
  default = ""
}

variable "sharepoint_base_folder" {
  description = "Must end in /_dev_test unless sharepoint_allow_live_folder is true."
  type        = string
  default     = ""
}

variable "sharepoint_allow_live_folder" {
  description = "SHAREPOINT_ALLOW_LIVE_FOLDER: allow a base folder that isn't _dev_test (the real one VIVE approved, 2026-10-20)."
  type        = bool
  default     = false
}
