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
    Name of the existing, empty resource group to deploy into. All
    resources inherit their region from this resource group's own
    location (via the azurerm_resource_group data source in main.tf) --
    there is no separate `location` variable. Before applying, verify in
    the Azure AI Foundry model catalog that Anthropic Claude models are
    actually offered in this resource group's region -- check with:
    az group show -n <name> --query location
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
  description = "Region for the App Service Plan and the Web App (which must share the Plan's region) -- separate from the resource group's own location. A resource group's location is just metadata; resources inside it can live in any region. Set to East US because that's where this subscription actually has compute quota for the P0v4 SKU (see app_service_sku)."
  type        = string
  default     = "eastus"
}

variable "sql_location" {
  description = "Region for the Azure SQL Server -- independent of app_service_location. This subscription returned 'ProvisioningDisabled' for Azure SQL in East US and East US 2 (a Microsoft-side restriction on this subscription/region pair, not an Azure Policy -- checked: none assigned), but a pre-existing SQL server in this same resource group (vive-reconciliation-server) proves West US 2 works."
  type        = string
  default     = "westus2"
}
