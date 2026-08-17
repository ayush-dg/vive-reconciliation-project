output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "acr_name" {
  value = azurerm_container_registry.acr.name
}

output "webapp_name" {
  value = azurerm_linux_web_app.app.name
}

output "webapp_url" {
  value = "https://${azurerm_linux_web_app.app.default_hostname}"
}

# Commented out along with azurerm_cognitive_account.foundry in main.tf --
# reusing the existing foundry-vive-recon resource, not one this config
# creates. var.foundry_endpoint is the connection detail now in use.
# output "foundry_account_name" {
#   value = azurerm_cognitive_account.foundry.name
# }
#
# output "foundry_endpoint" {
#   value = azurerm_cognitive_account.foundry.endpoint
# }

output "storage_account_name" {
  value = azurerm_storage_account.storage.name
}

output "sql_server_fqdn" {
  value = azurerm_mssql_server.sql.fully_qualified_domain_name
}

output "sql_database_name" {
  value = azurerm_mssql_database.sql.name
}

output "sql_admin_username" {
  value = azurerm_mssql_server.sql.administrator_login
}

# Sensitive -- retrieve with: terraform output -raw sql_admin_password
output "sql_admin_password" {
  value     = random_password.sql_admin.result
  sensitive = true
}
