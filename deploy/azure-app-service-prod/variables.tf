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
  description = "Tag of the vive-reconciliation image in ACR to deploy."
  type        = string
  default     = "latest"
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
