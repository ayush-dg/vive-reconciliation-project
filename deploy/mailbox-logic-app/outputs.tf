output "notify_workflow_name" {
  value = "${var.name_prefix}-notify"
}

output "subscription_workflow_name" {
  value = "${var.name_prefix}-subscription"
}

output "upload_sas_expiry" {
  description = "Re-apply before this date so uploads keep working."
  value       = data.azurerm_storage_account_blob_container_sas.upload.expiry
}
