data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

# Dedicated, shorter suffix for the mailbox storage account -- "vivecollisionprod"
# (17 chars) + "mbx" (3) + this leaves only 4 chars of budget under the
# storage account's 24-char hard limit, too tight to share the 6-char
# suffix everything else uses.
resource "random_string" "storage_suffix" {
  length  = 4
  special = false
  upper   = false
}

locals {
  suffix = random_string.suffix.result

  # ACR names are globally-unique, lowercase alphanumeric only (no
  # hyphens) -- name_prefix allows hyphens for readability elsewhere (SQL
  # server, plan), so strip them here.
  alnum_prefix = replace(var.name_prefix, "-", "")
}

# --- Container registry: holds the built vive-reconciliation prod image ---
# admin_enabled = true (rather than managed-identity + AcrPull role
# assignment) -- same constraint as the dev/demo config: this account is
# Contributor-only, and role assignments need Owner/User Access
# Administrator.
resource "azurerm_container_registry" "acr" {
  name                = "${local.alnum_prefix}acr${local.suffix}"
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.app_service_location
  sku                 = "Basic"
  admin_enabled       = true
}

# --- Azure SQL Database: backing store for src/lakehouse/connection.py,
# selected automatically once AZURE_SQL_SERVER is set (get_connection()'s
# _using_azure_sql()). Serves Bronze/Silver/Gold + the 4 Recon tables not
# yet cut over to Fabric (jobs, exception_dispositions, users,
# ai_audit_log). ---
resource "random_password" "sql_admin" {
  length      = 24
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
  min_special = 1
  # Azure SQL rejects some special characters -- keep to a known-safe set.
  override_special = "!#$%&*-_="
}

resource "azurerm_mssql_server" "sql" {
  name                         = "${var.name_prefix}-sql-${local.suffix}"
  resource_group_name          = data.azurerm_resource_group.this.name
  location                     = var.sql_location
  version                      = "12.0"
  administrator_login          = "viveadmin"
  administrator_login_password = random_password.sql_admin.result
  minimum_tls_version          = "1.2"
}

resource "azurerm_mssql_database" "sql" {
  name        = "${var.name_prefix}-db"
  server_id   = azurerm_mssql_server.sql.id
  sku_name    = "Basic"
  max_size_gb = 2
}

# Required or nothing can connect at all -- a new Azure SQL Server has zero
# firewall rules by default. Both rules are free (access-control metadata
# on the server, not a billable resource).
resource "azurerm_mssql_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.sql.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_mssql_firewall_rule" "allow_client" {
  name             = "AllowClientIP"
  server_id        = azurerm_mssql_server.sql.id
  start_ip_address = var.sql_admin_client_ip
  end_ip_address   = var.sql_admin_client_ip
}

# --- Mailbox sync storage: mirrors the existing viveinsightstatements
# account (StorageV2, RAGRS, Hot, TLS1.2, no public blob access) --
# backs the mailbox-sync Function App's AzureWebJobsStorage + deployment
# package container, and holds the 'raw' container the function writes
# PDFs into (azure-functions/mailbox-sync/function_app.py). ---
resource "azurerm_storage_account" "mailbox" {
  name                            = "${local.alnum_prefix}mbx${random_string.storage_suffix.result}"
  resource_group_name             = data.azurerm_resource_group.this.name
  location                        = var.mailbox_storage_location
  account_tier                    = "Standard"
  account_replication_type        = "RAGRS"
  account_kind                    = "StorageV2"
  access_tier                     = "Hot"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
}

resource "azurerm_storage_container" "mailbox_raw" {
  name                  = var.mailbox_container_name
  storage_account_id    = azurerm_storage_account.mailbox.id
  container_access_type = "private"
}

# Flex Consumption function apps deploy from a package sitting in blob
# storage -- unlike the portal's create wizard, Terraform doesn't
# auto-create this container, so it's provisioned explicitly here.
resource "azurerm_storage_container" "mailbox_deployment" {
  name                  = "app-package-mailbox-sync"
  storage_account_id    = azurerm_storage_account.mailbox.id
  container_access_type = "private"
}

resource "azurerm_application_insights" "mailbox_sync" {
  name                = "${var.name_prefix}-mailbox-sync-ai"
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.function_plan_location
  application_type    = "web"
}

# --- Mailbox sync Function App (Flex Consumption, matching the existing
# vive-mailbox-sync: kind functionapp,linux, Python 3.12, FC1 plan). ---
resource "azurerm_service_plan" "mailbox_sync" {
  name                = "${var.name_prefix}-mailbox-sync-plan"
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.function_plan_location
  os_type             = "Linux"
  sku_name            = "FC1"
}

resource "azurerm_function_app_flex_consumption" "mailbox_sync" {
  name                = "${var.name_prefix}-mailbox-sync"
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.function_plan_location
  service_plan_id     = azurerm_service_plan.mailbox_sync.id

  storage_container_type      = "blobContainer"
  storage_container_endpoint  = "${azurerm_storage_account.mailbox.primary_blob_endpoint}${azurerm_storage_container.mailbox_deployment.name}"
  storage_authentication_type = "StorageAccountConnectionString"
  storage_access_key          = azurerm_storage_account.mailbox.primary_access_key

  runtime_name    = "python"
  runtime_version = "3.12"

  site_config {
    application_insights_connection_string = azurerm_application_insights.mailbox_sync.connection_string
  }

  app_settings = {
    AzureWebJobsStorage = azurerm_storage_account.mailbox.primary_connection_string

    AZURE_TENANT_ID     = var.mailbox_graph_tenant_id
    AZURE_CLIENT_ID     = var.mailbox_graph_client_id
    AZURE_CLIENT_SECRET = var.mailbox_graph_client_secret

    TARGET_MAILBOX      = var.mailbox_target_mailbox
    MAILBOX_CONTAINER   = var.mailbox_container_name
    WATERMARK_BLOB_PATH = var.mailbox_watermark_blob_path
  }
}

# Function-level key for auth_level=FUNCTION on the /api/sync route
# (function_app.py) -- the main web app needs this to call the function
# (MAILBOX_SYNC_FUNCTION_KEY below).
data "azurerm_function_app_host_keys" "mailbox_sync" {
  name                = azurerm_function_app_flex_consumption.mailbox_sync.name
  resource_group_name = data.azurerm_resource_group.this.name
}

# --- App Service ---
resource "random_password" "web_session_secret" {
  length  = 32
  special = false
}

resource "azurerm_service_plan" "plan" {
  name                = "${var.name_prefix}-plan"
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.app_service_location
  os_type             = "Linux"
  sku_name            = var.app_service_sku
}

resource "azurerm_linux_web_app" "app" {
  name                = var.app_service_name
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.app_service_location # must match azurerm_service_plan.plan's region
  service_plan_id     = azurerm_service_plan.plan.id

  site_config {
    always_on = true

    # Overrides the image's CMD (`tail -f /dev/null`, a dev-only idle
    # command for docker-compose). App Service's Linux custom-container
    # "Startup Command" field does naive whitespace tokenization with no
    # quote-awareness -- a compound `cmd1 && cmd2` string breaks. Baking
    # the compound logic into a script and invoking it as one token
    # sidesteps that entirely.
    app_command_line = "sh /app/deploy/azure-app-service-prod/container-start.sh"

    application_stack {
      docker_image_name        = "vive-reconciliation:${var.docker_image_tag}"
      docker_registry_url      = "https://${azurerm_container_registry.acr.login_server}"
      docker_registry_username = azurerm_container_registry.acr.admin_username
      docker_registry_password = azurerm_container_registry.acr.admin_password
    }
  }

  app_settings = {
    WEBSITES_PORT = "8000"

    WEB_SESSION_SECRET = random_password.web_session_secret.result

    AZURE_SQL_SERVER   = azurerm_mssql_server.sql.fully_qualified_domain_name
    AZURE_SQL_DATABASE = azurerm_mssql_database.sql.name
    AZURE_SQL_USERNAME = azurerm_mssql_server.sql.administrator_login
    AZURE_SQL_PASSWORD = random_password.sql_admin.result

    # Existing Claude key/endpoint reused -- no new Foundry account here.
    AZURE_CLAUDE_API_KEY           = var.claude_api_key
    AZURE_CLAUDE_ENDPOINT          = var.claude_endpoint
    AZURE_CLAUDE_SONNET_DEPLOYMENT = var.claude_sonnet_deployment_name
    AZURE_CLAUDE_DEPLOYMENT        = var.claude_haiku_deployment_name

    # No archival storage account for prod (removed 2026-09-23, not
    # needed) -- src/storage/blob_client.py's PDF archival step is
    # best-effort/non-fatal when AZURE_BLOB_CONNECTION_STRING is unset
    # ("Warning: PDF was not archived to Blob Storage -- continuing
    # without it"), so this is a safe, deliberate gap, not a bug.

    # Wired to the mailbox-sync Function App provisioned above --
    # web/routers/mailbox_sync.py's "Sync Outlook Now" button calls this.
    MAILBOX_SYNC_FUNCTION_URL            = "https://${azurerm_function_app_flex_consumption.mailbox_sync.default_hostname}/api/sync"
    MAILBOX_SYNC_FUNCTION_KEY            = data.azurerm_function_app_host_keys.mailbox_sync.default_function_key
    AZURE_BLOB_MAILBOX_CONNECTION_STRING = azurerm_storage_account.mailbox.primary_connection_string

    # Fabric passthrough -- empty until the prod Fabric workspace/items are
    # created by hand and these variables are filled in (see variables.tf).
    # Empty string is a supported "not configured" state in
    # src/lakehouse/connection.py / src/lakehouse/fabric_sql.py, not a
    # placeholder that breaks anything.
    FABRIC_TENANT_ID       = var.fabric_tenant_id
    FABRIC_CLIENT_ID       = var.fabric_client_id
    FABRIC_CLIENT_SECRET   = var.fabric_client_secret
    FABRIC_WORKSPACE_ID    = var.fabric_workspace_id
    FABRIC_LAKEHOUSE_NAME  = var.fabric_lakehouse_name
    FABRIC_LAKEHOUSE_ID    = var.fabric_lakehouse_id
    FABRIC_WAREHOUSE_NAME  = var.fabric_warehouse_name
    FABRIC_SQL_ENDPOINT    = var.fabric_sql_endpoint
    FABRIC_SQL_ENDPOINT_ID = var.fabric_sql_endpoint_id
    FABRIC_SQLDB_ENDPOINT  = var.fabric_sqldb_endpoint
    FABRIC_SQLDB_NAME      = var.fabric_sqldb_name
  }
}
