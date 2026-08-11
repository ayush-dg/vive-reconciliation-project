# Lightweight-demo variant: no Azure SQL, no Fabric SQL database item.
# Leaving AZURE_SQL_SERVER unset makes src/lakehouse/connection.py fall back
# to its built-in SQLite backend for every table (Bronze/Silver/Gold + all
# Recon tables), which also happens to sidestep the AzureCliCredential
# auth path in get_fabric_connection() — that path requires an interactive
# `az login` session and does not work inside an App Service container.

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
  description = "App Service Plan SKU. Must be B1 or higher -- Free/Shared tiers don't support Always On, which the app's in-process worker (web/app.py's lifespan-started worker pool) needs to survive idling."
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

variable "gpt5_mini_deployment_name" {
  description = "Deployment name for gpt-5-mini inside the AI Foundry resource -- must match whatever you named it when you created the deployment in the Foundry portal. Used instead of Claude because this subscription has 0 quota for every Claude model in every region -- see config/ai/active_provider.json's _comment."
  type        = string
  default     = "gpt-5-mini"
}
