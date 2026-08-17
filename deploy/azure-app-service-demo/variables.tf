# Lightweight-demo variant: no Fabric SQL database item. A real Azure SQL
# Database is provisioned below (AZURE_SQL_* app settings) so
# src/lakehouse/connection.py uses it for every table (Bronze/Silver/Gold +
# all Recon tables) instead of SQLite. This still sidesteps the
# AzureCliCredential auth path in get_fabric_connection() — that path
# requires an interactive `az login` session and does not work inside an
# App Service container.

variable "subscription_id" {
  description = "Azure subscription ID to deploy into. Pinned explicitly rather than left to whatever `az account set` last pointed at, since more than one subscription is available in this tenant. Check with: az account list -o table"
  type        = string
}

variable "resource_group_name" {
  description = <<-EOT
    Name of the existing resource group to deploy into. Does not need to
    be empty -- this config is designed to coexist with pre-existing
    resources it does not manage (e.g. an existing Azure AI Foundry
    account; see foundry_endpoint / foundry_api_key below). Before
    applying, verify in the Azure AI Foundry model catalog that Anthropic
    Claude models are actually offered in this resource group's region --
    check with: az group show -n <name> --query location
  EOT
  type        = string
}

variable "name_prefix" {
  description = "Short prefix for resource names. Lowercase alphanumeric only (used in globally-unique names like the storage account and ACR)."
  type        = string
  default     = "viverecondemo"

  validation {
    condition     = can(regex("^[a-z0-9]+$", var.name_prefix))
    error_message = "name_prefix must be lowercase letters and digits only."
  }
}

variable "app_service_sku" {
  description = "App Service Plan SKU. Must be B1 or higher -- Free/Shared tiers don't support Always On, which the app's in-process worker (web/app.py's lifespan-started worker pool) needs to survive idling. This subscription has zero 'Total VMs' compute quota for the B-family VMs Basic (B1) uses, in every region checked (East US, East US 2) -- Premium v4's P0v4 SKU uses a different VM family that this subscription does have quota for in East US. Costs more than B1; check current Premium v4 pricing before assuming it's still cheap."
  type        = string
  default     = "B1"
}

variable "docker_image_tag" {
  description = "Tag of the vive-reconciliation image in ACR to deploy."
  type        = string
  default     = "latest"
}

variable "web_session_secret" {
  description = "Secret key for FastAPI's SessionMiddleware (WEB_SESSION_SECRET). Generate with: openssl rand -hex 32"
  type        = string
  sensitive   = true
}

variable "claude_sonnet_deployment_name" {
  description = "Deployment name for Claude Sonnet 4.6 inside the AI Foundry resource -- must match whatever you named it when you created the deployment in the Foundry portal (see README.md step 3)."
  type        = string
  default     = "claude-sonnet-4-6"
}

variable "claude_haiku_deployment_name" {
  description = "Deployment name for Claude Haiku 4.5 inside the AI Foundry resource -- exception/--explain narrative only, never used for extraction. Must match whatever you named it when you created the deployment in the Foundry portal (see README.md step 3)."
  type        = string
  default     = "claude-haiku-4-5"
}

variable "sql_admin_client_ip" {
  description = "Your own public IPv4 address, so the voucher-loading script (run from your machine, not from inside Azure) can reach the new Azure SQL Database directly. Find it with: curl ifconfig.me"
  type        = string
}

variable "app_service_location" {
  description = "Region for the App Service Plan and the Web App (which must share the Plan's region) -- separate from the resource group's own location. A resource group's location is just metadata; resources inside it can live in any region. Set to West US 2 to match rg-vive-if -- re-verify compute quota for app_service_sku under this subscription before applying, since the previous East US pin was specific to the old subscription's quota."
  type        = string
  default     = "westus2"
}

variable "foundry_endpoint" {
  description = "Base Anthropic-compatible endpoint URL for the existing Azure AI Foundry resource being reused (foundry-vive-recon in rg-vive-recon, East US 2), e.g. https://foundry-vive-recon.services.ai.azure.com/anthropic -- the base endpoint only, NOT the full inference URL (no /v1/messages suffix). claude_sonnet_client.py passes this straight through as AnthropicFoundry(base_url=...); the SDK appends the request path itself, and the deployment name is sent separately as the request's `model` field (see claude_sonnet_deployment_name), never appended to the URL. This config does not provision a Foundry account -- see the commented-out azurerm_cognitive_account.foundry block in main.tf."
  type        = string
  sensitive   = true
}

variable "foundry_api_key" {
  description = "API key for the existing Azure AI Foundry resource being reused (foundry-vive-recon). Retrieve from that resource's Keys and Endpoint blade in the portal -- not generated by this Terraform config."
  type        = string
  sensitive   = true
}

variable "sql_location" {
  description = "Region for the Azure SQL Server -- independent of app_service_location. This subscription returned 'ProvisioningDisabled' for Azure SQL in East US and East US 2 (a Microsoft-side restriction on this subscription/region pair, not an Azure Policy -- checked: none assigned), but a pre-existing SQL server in this same resource group (vive-reconciliation-server) proves West US 2 works."
  type        = string
  default     = "westus2"
}
