data "azurerm_subscription" "current" {}

variable "tag_policy_enabled" {
  type        = bool
  description = "Enable the tag auto-fill policy assignment (SecurityControl/CostControl)."
  default     = true
}

variable "tag_policy_scope" {
  type        = string
  description = "Scope for the tag policy assignment: 'resource_group' or 'subscription'."
  default     = "resource_group"

  validation {
    condition     = contains(["resource_group", "subscription"], var.tag_policy_scope)
    error_message = "tag_policy_scope must be one of: resource_group, subscription."
  }
}

locals {
  tag_policy_rg_scope_id  = azurerm_resource_group.rg.id
  tag_policy_sub_scope_id = data.azurerm_subscription.current.id
}

resource "azurerm_policy_definition" "add_security_cost_ignore_tags" {
  name         = "add-security-costcontrol-ignore-tags"
  policy_type  = "Custom"
  mode         = "All"
  display_name = "Add Security Control and Cost Control Ignore Tags"
  description  = "This policy automatically adds 'SecurityControl' and 'CostControl' tags with value 'ignore' to all resources except subscriptions, resource groups, deployments, and management groups."

  metadata = jsonencode({
    category = "Tags"
    version  = "1.0.0"
  })

  parameters = jsonencode({})

  policy_rule = jsonencode({
    if = {
      allOf = [
        {
          field = "type"
          notIn = [
            "Microsoft.Resources/subscriptions",
            "Microsoft.Resources/resourceGroups",
            "Microsoft.Resources/deployments",
            "Microsoft.Management/managementGroups",
          ]
        },
        {
          anyOf = [
            {
              field  = "tags['SecurityControl']"
              exists = "false"
            },
            {
              field  = "tags['CostControl']"
              exists = "false"
            },
          ]
        },
      ]
    }
    then = {
      effect = "modify"
      details = {
        roleDefinitionIds = [
          "/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c",
        ]
        operations = [
          {
            operation = "addOrReplace"
            field     = "tags['SecurityControl']"
            value     = "ignore"
          },
          {
            operation = "addOrReplace"
            field     = "tags['CostControl']"
            value     = "ignore"
          },
        ]
      }
    }
  })
}

resource "azurerm_resource_group_policy_assignment" "add_security_cost_ignore_tags_rg" {
  count                = var.tag_policy_enabled && var.tag_policy_scope == "resource_group" ? 1 : 0
  name                 = "add-security-costcontrol-ignore-tags"
  resource_group_id    = azurerm_resource_group.rg.id
  policy_definition_id = azurerm_policy_definition.add_security_cost_ignore_tags.id
  location             = var.location

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_subscription_policy_assignment" "add_security_cost_ignore_tags_sub" {
  count                = var.tag_policy_enabled && var.tag_policy_scope == "subscription" ? 1 : 0
  name                 = "add-security-costcontrol-ignore-tags"
  subscription_id      = data.azurerm_subscription.current.subscription_id
  policy_definition_id = azurerm_policy_definition.add_security_cost_ignore_tags.id
  location             = var.location

  identity {
    type = "SystemAssigned"
  }
}

# The assignment's managed identity needs the role specified in the policy's modify.details.roleDefinitionIds.
resource "azurerm_role_assignment" "add_security_cost_ignore_tags_role_rg" {
  count = var.tag_policy_enabled && var.tag_policy_scope == "resource_group" ? 1 : 0

  scope              = local.tag_policy_rg_scope_id
  role_definition_id = "/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c"
  principal_id       = azurerm_resource_group_policy_assignment.add_security_cost_ignore_tags_rg[0].identity[0].principal_id
}

resource "azurerm_role_assignment" "add_security_cost_ignore_tags_role_sub" {
  count = var.tag_policy_enabled && var.tag_policy_scope == "subscription" ? 1 : 0

  scope              = local.tag_policy_sub_scope_id
  role_definition_id = "/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c"
  principal_id       = azurerm_subscription_policy_assignment.add_security_cost_ignore_tags_sub[0].identity[0].principal_id
}

# Optional: remediate existing resources that are already missing the tags.
resource "azurerm_resource_group_policy_remediation" "add_security_cost_ignore_tags_rg" {
  count = var.tag_policy_enabled && var.tag_policy_scope == "resource_group" ? 1 : 0

  name                 = "remediate-add-ignore-tags"
  resource_group_id    = azurerm_resource_group.rg.id
  policy_assignment_id = azurerm_resource_group_policy_assignment.add_security_cost_ignore_tags_rg[0].id

  depends_on = [azurerm_role_assignment.add_security_cost_ignore_tags_role_rg]
}

resource "azurerm_subscription_policy_remediation" "add_security_cost_ignore_tags_sub" {
  count = var.tag_policy_enabled && var.tag_policy_scope == "subscription" ? 1 : 0

  name                 = "remediate-add-ignore-tags"
  subscription_id      = data.azurerm_subscription.current.subscription_id
  policy_assignment_id = azurerm_subscription_policy_assignment.add_security_cost_ignore_tags_sub[0].id

  depends_on = [azurerm_role_assignment.add_security_cost_ignore_tags_role_sub]
}
