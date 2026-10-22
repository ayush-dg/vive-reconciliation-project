# The workflow definitions live as ARM templates in workflows/ -- the
# Logic App designer and code view both read and write that JSON, so it
# stays the one copy to edit. Terraform deploys the notify Logic App
# first, then the subscription Logic App (whose first run registers the
# Graph subscription, so the notify side must already be live).

locals {
  storage_rg    = coalesce(var.storage_resource_group_name, var.resource_group_name)
  container_url = "https://${var.storage_account_name}.blob.core.windows.net/${var.container_name}"
  notify_out    = jsondecode(azurerm_resource_group_template_deployment.notify.output_content)
}

data "azurerm_storage_account" "mailbox" {
  name                = var.storage_account_name
  resource_group_name = local.storage_rg
}

# The notify Logic App uploads with a container SAS that can only create and
# write blobs (no read, list or delete) -- a managed identity would need a
# role assignment, which Contributor can't grant. Made from the account key,
# as the Function's own connection string is. A re-apply after
# sas_rotation_days issues a fresh one; each is valid for a year.
resource "time_rotating" "sas" {
  rotation_days = var.sas_rotation_days
}

data "azurerm_storage_account_blob_container_sas" "upload" {
  connection_string = data.azurerm_storage_account.mailbox.primary_connection_string
  container_name    = var.container_name
  https_only        = true
  start             = time_rotating.sas.rfc3339
  expiry            = timeadd(time_rotating.sas.rfc3339, "8760h")

  permissions {
    read   = false
    add    = false
    create = true
    write  = true
    delete = false
    list   = false
  }
}

# Graph echoes this back on every notification; the notify Logic App drops
# any notification that doesn't carry it.
resource "random_password" "client_state" {
  length  = 40
  special = false
}

resource "azurerm_resource_group_template_deployment" "notify" {
  name                = "${var.name_prefix}-notify"
  resource_group_name = var.resource_group_name
  deployment_mode     = "Incremental"
  template_content    = file("${path.module}/workflows/notify.json")
  parameters_content = jsonencode({
    workflowName         = { value = "${var.name_prefix}-notify" }
    location             = { value = var.location }
    tenantId             = { value = var.tenant_id }
    graphClientId        = { value = var.graph_client_id }
    graphClientSecret    = { value = var.graph_client_secret }
    targetMailbox        = { value = var.target_mailbox }
    blobContainerUrl     = { value = local.container_url }
    blobSas              = { value = data.azurerm_storage_account_blob_container_sas.upload.sas }
    webappAutosyncUrl    = { value = var.webapp_autosync_url }
    webappAutosyncSecret = { value = var.webapp_autosync_secret }
    clientState          = { value = random_password.client_state.result }
  })
}

resource "azurerm_resource_group_template_deployment" "subscription" {
  name                = "${var.name_prefix}-subscription"
  resource_group_name = var.resource_group_name
  deployment_mode     = "Incremental"
  template_content    = file("${path.module}/workflows/subscription.json")
  parameters_content = jsonencode({
    workflowName        = { value = "${var.name_prefix}-subscription" }
    location            = { value = var.location }
    tenantId            = { value = var.tenant_id }
    graphClientId       = { value = var.graph_client_id }
    graphClientSecret   = { value = var.graph_client_secret }
    targetMailbox       = { value = var.target_mailbox }
    notificationUrl     = { value = local.notify_out.callbackUrl.value }
    clientState         = { value = random_password.client_state.result }
    subscriptionMinutes = { value = var.subscription_minutes }
  })
}
