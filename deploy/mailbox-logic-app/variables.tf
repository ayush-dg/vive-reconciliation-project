# Instant mailbox intake: a Graph change notification fires the moment a
# message lands in the statements mailbox, and a Logic App writes its PDF
# attachments to the same raw container (same blob path format) as the
# mailbox-sync Function, then asks the web app to queue them. The
# Function's 30-minute timer is untouched and keeps running as the
# backstop. One state per environment -- see README.md.

variable "subscription_id" {
  description = "Azure subscription ID to deploy into. Check with: az account show"
  type        = string
}

variable "resource_group_name" {
  description = "Existing resource group the Logic Apps go into."
  type        = string
}

variable "location" {
  description = "Region for the Logic Apps."
  type        = string
  default     = "westus"
}

variable "name_prefix" {
  description = "Logic App names become <prefix>-notify and <prefix>-subscription."
  type        = string
  default     = "vive-mailbox"
}

variable "storage_account_name" {
  description = "The mailbox storage account the mailbox-sync Function writes to (its AzureWebJobsStorage)."
  type        = string
}

variable "storage_resource_group_name" {
  description = "Resource group of storage_account_name. Defaults to resource_group_name."
  type        = string
  default     = null
}

variable "container_name" {
  description = "Container the PDFs go into -- the Function's MAILBOX_CONTAINER."
  type        = string
  default     = "raw"
}

variable "target_mailbox" {
  description = "The mailbox to watch -- the Function's TARGET_MAILBOX."
  type        = string
}

variable "tenant_id" {
  description = "Entra tenant of the Graph app registration -- the Function's AZURE_TENANT_ID."
  type        = string
}

variable "graph_client_id" {
  description = "App registration with Mail.Read (application) -- the Function's AZURE_CLIENT_ID."
  type        = string
}

variable "graph_client_secret" {
  description = "That app registration's secret -- the Function's AZURE_CLIENT_SECRET."
  type        = string
  sensitive   = true
}

variable "webapp_autosync_url" {
  description = "The web app's /mailbox-sync/auto URL -- the Function's WEBAPP_AUTOSYNC_URL."
  type        = string
}

variable "webapp_autosync_secret" {
  description = "Sent as x-vive-autosync-secret -- the Function's MAILBOX_AUTOSYNC_SECRET."
  type        = string
  sensitive   = true
}

variable "sas_rotation_days" {
  description = "A terraform apply this many days after the upload SAS was issued replaces it (each SAS is valid 365 days)."
  type        = number
  default     = 180
}

variable "subscription_minutes" {
  description = "How far ahead each create/renew sets the Graph subscription's expiry. Graph allows at most 10070 minutes for mail; renewal runs every 12 hours."
  type        = number
  default     = 4320
}
