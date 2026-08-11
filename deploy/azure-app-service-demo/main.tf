data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

locals {
  suffix = random_string.suffix.result
}

# --- Container registry: holds the built vive-reconciliation image ---
# admin_enabled = true (rather than a managed-identity + AcrPull role
# assignment) because granting RBAC roles requires
# Microsoft.Authorization/roleAssignments/write, which needs Owner or User
# Access Administrator -- not available on this account (Contributor
# only). Admin credentials only need the same permissions used to create
# the registry itself. Fine for a demo; revisit for anything longer-lived.
resource "azurerm_container_registry" "acr" {
  name                = "${var.name_prefix}acr${local.suffix}"
  resource_group_name = data.azurerm_resource_group.this.name
  location            = data.azurerm_resource_group.this.location
  sku                 = "Basic"
  admin_enabled       = true
}

# --- Blob storage: archival container used by src/storage/blob_client.py ---
resource "azurerm_storage_account" "storage" {
  name                     = "${var.name_prefix}st${local.suffix}"
  resource_group_name      = data.azurerm_resource_group.this.name
  location                 = data.azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_storage_container" "vendor_statements" {
  name                  = "vendor-statements"
  storage_account_id    = azurerm_storage_account.storage.id
  container_access_type = "private"
}

# --- Azure AI Foundry (Cognitive Services "AIServices" account) ---
# This resource is created here, but the Claude Haiku 4.5 / Claude Sonnet 4.6
# *deployments* inside it are NOT created by this Terraform config -- see
# README.md for why, and for the manual portal steps to add them.
resource "azurerm_cognitive_account" "foundry" {
  name                  = "${var.name_prefix}-foundry-${local.suffix}"
  resource_group_name   = data.azurerm_resource_group.this.name
  location              = data.azurerm_resource_group.this.location
  kind                  = "AIServices"
  sku_name              = "S0"
  custom_subdomain_name = "${var.name_prefix}-foundry-${local.suffix}"
}

# --- App Service ---
resource "azurerm_service_plan" "plan" {
  name                = "${var.name_prefix}-plan"
  resource_group_name = data.azurerm_resource_group.this.name
  location            = data.azurerm_resource_group.this.location
  os_type             = "Linux"
  sku_name            = var.app_service_sku
}

resource "azurerm_linux_web_app" "app" {
  name                = "${var.name_prefix}-${local.suffix}"
  resource_group_name = data.azurerm_resource_group.this.name
  location            = data.azurerm_resource_group.this.location
  service_plan_id     = azurerm_service_plan.plan.id

  site_config {
    always_on = true

    # Overrides the image's CMD (which is `tail -f /dev/null` -- a dev-only
    # idle command the same Dockerfile uses for docker-compose so you can
    # `docker exec` into it locally, see Dockerfile / docker-compose.yml).
    # Deliberately not changed in the Dockerfile itself so local dev is
    # unaffected -- this override is App-Service-only.
    #
    # Runs container-start.sh (schema migration, then uvicorn -- see that
    # file for why both steps are needed). Invoked as two plain tokens
    # with no whitespace inside either one, deliberately NOT as a `cmd1 &&
    # cmd2` string: confirmed empirically that Azure App Service's Linux
    # custom-container "Startup Command" field does naive whitespace
    # tokenization with no quote-awareness at all (neither single- nor
    # double-quoted compound commands survived -- both broke, one
    # silently exiting 0 after only running the first fragment, the other
    # erroring on `sh -c`'s mis-tokenized argument). A single script
    # invocation sidesteps the whole problem.
    #
    # No Azure Files mount for the DB -- SQLite's WAL journal mode
    # (connection.py's get_connection()) needs POSIX file-locking
    # semantics that Azure Files' SMB mount doesn't reliably provide, and
    # crash-looped with "unable to open database file" when tried. The DB
    # is ephemeral (wiped on restart/redeploy) as a result -- see
    # README.md's "Where the database lives" for the real-persistence
    # path (Azure SQL) if that's needed later.
    app_command_line = "sh /app/deploy/azure-app-service-demo/container-start.sh"

    application_stack {
      docker_image_name        = "vive-reconciliation:${var.docker_image_tag}"
      docker_registry_url      = "https://${azurerm_container_registry.acr.login_server}"
      docker_registry_username = azurerm_container_registry.acr.admin_username
      docker_registry_password = azurerm_container_registry.acr.admin_password
    }
  }

  app_settings = {
    WEBSITES_PORT = "8000"

    WEB_SESSION_SECRET = var.web_session_secret

    # Note: no AZURE_SQL_* or FABRIC_SQLDB_* settings -- leaving those unset
    # is what puts src/lakehouse/connection.py into its SQLite fallback for
    # this lightweight demo. Do not add empty-string placeholders for them;
    # _using_azure_sql() checks whether the var exists at all.

    # Claude Haiku/Sonnet deployments were never created (0 quota across
    # every region/SKU for this subscription -- see the conversation this
    # config came out of). No AZURE_CLAUDE_* settings for the same reason
    # as leaving AZURE_SQL_* unset: pointing them at a deployment that
    # doesn't exist would make every extraction wait out a real network
    # failure before falling back, instead of nothing being attempted at
    # all. config/ai/active_provider.json's provider_chain was switched to
    # azure_gpt5_mini as a result -- see that file's _comment for why and
    # how to revert once Claude quota is approved.
    AZURE_OPENAI_ENDPOINT             = azurerm_cognitive_account.foundry.endpoint
    AZURE_OPENAI_API_KEY              = azurerm_cognitive_account.foundry.primary_access_key
    AZURE_OPENAI_DEPLOYMENT_GPT5_MINI = var.gpt5_mini_deployment_name

    AZURE_BLOB_CONNECTION_STRING = azurerm_storage_account.storage.primary_connection_string
  }
}
