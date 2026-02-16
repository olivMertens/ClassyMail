data "azurerm_subscription" "current" {}

variable "tag_policy_enabled" {
  type        = bool
  description = "Enable the tag auto-fill policy assignment (G2S mandatory tags: cp-code-sa, cp-deploiement, cp-environnement, cp-proprietaire, cp-responsable, cp-supervision)."
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

resource "azurerm_policy_definition" "add_g2s_mandatory_tags" {
  count        = var.g2s_tags_enabled ? 1 : 0
  name         = "add-g2s-mandatory-tags"
  policy_type  = "Custom"
  mode         = "All"
  display_name = "Add G2S Mandatory Tags"
  description  = "This policy automatically adds mandatory G2S tags (cp-code-sa, cp-deploiement, cp-environnement, cp-proprietaire, cp-responsable, cp-supervision) to all resources except subscriptions, resource groups, deployments, and management groups."

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
              field  = "tags['cp-code-sa']"
              exists = "false"
            },
            {
              field  = "tags['cp-deploiement']"
              exists = "false"
            },
            {
              field  = "tags['cp-environnement']"
              exists = "false"
            },
            {
              field  = "tags['cp-proprietaire']"
              exists = "false"
            },
            {
              field  = "tags['cp-responsable']"
              exists = "false"
            },
            {
              field  = "tags['cp-supervision']"
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
            field     = "tags['cp-code-sa']"
            value     = "devin"
          },
          {
            operation = "addOrReplace"
            field     = "tags['cp-deploiement']"
            value     = "terraform"
          },
          {
            operation = "addOrReplace"
            field     = "tags['cp-environnement']"
            value     = "d"
          },
          {
            operation = "addOrReplace"
            field     = "tags['cp-proprietaire']"
            value     = "g2s-dtpo-iaf"
          },
          {
            operation = "addOrReplace"
            field     = "tags['cp-responsable']"
            value     = "g2s-dtpo-iaf"
          },
          {
            operation = "addOrReplace"
            field     = "tags['cp-supervision']"
            value     = "oui"
          },
        ]
      }
    }
  })
}

resource "azurerm_resource_group_policy_assignment" "add_g2s_mandatory_tags_rg" {
  count                = var.g2s_tags_enabled && var.tag_policy_enabled && var.tag_policy_scope == "resource_group" ? 1 : 0
  name                 = "add-g2s-mandatory-tags"
  resource_group_id    = azurerm_resource_group.rg.id
  policy_definition_id = azurerm_policy_definition.add_g2s_mandatory_tags[0].id
  location             = var.location

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_subscription_policy_assignment" "add_g2s_mandatory_tags_sub" {
  count                = var.g2s_tags_enabled && var.tag_policy_enabled && var.tag_policy_scope == "subscription" ? 1 : 0
  name                 = "add-g2s-mandatory-tags"
  subscription_id      = data.azurerm_subscription.current.subscription_id
  policy_definition_id = azurerm_policy_definition.add_g2s_mandatory_tags[0].id
  location             = var.location

  identity {
    type = "SystemAssigned"
  }
}

# The assignment's managed identity needs the role specified in the policy's modify.details.roleDefinitionIds.
resource "azurerm_role_assignment" "add_g2s_mandatory_tags_role_rg" {
  count = var.g2s_tags_enabled && var.tag_policy_enabled && var.tag_policy_scope == "resource_group" ? 1 : 0

  scope              = local.tag_policy_rg_scope_id
  role_definition_id = "/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c"
  principal_id       = azurerm_resource_group_policy_assignment.add_g2s_mandatory_tags_rg[0].identity[0].principal_id
}

resource "azurerm_role_assignment" "add_g2s_mandatory_tags_role_sub" {
  count = var.g2s_tags_enabled && var.tag_policy_enabled && var.tag_policy_scope == "subscription" ? 1 : 0

  scope              = local.tag_policy_sub_scope_id
  role_definition_id = "/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c"
  principal_id       = azurerm_subscription_policy_assignment.add_g2s_mandatory_tags_sub[0].identity[0].principal_id
}

# Optional: remediate existing resources that are already missing the tags.
resource "azurerm_resource_group_policy_remediation" "add_g2s_mandatory_tags_rg" {
  count = var.g2s_tags_enabled && var.tag_policy_enabled && var.tag_policy_scope == "resource_group" ? 1 : 0

  name                 = "remediate-add-g2s-tags"
  resource_group_id    = azurerm_resource_group.rg.id
  policy_assignment_id = azurerm_resource_group_policy_assignment.add_g2s_mandatory_tags_rg[0].id

  depends_on = [azurerm_role_assignment.add_g2s_mandatory_tags_role_rg]
}

resource "azurerm_subscription_policy_remediation" "add_g2s_mandatory_tags_sub" {
  count = var.g2s_tags_enabled && var.tag_policy_enabled && var.tag_policy_scope == "subscription" ? 1 : 0

  name                 = "remediate-add-g2s-tags"
  subscription_id      = data.azurerm_subscription.current.subscription_id
  policy_assignment_id = azurerm_subscription_policy_assignment.add_g2s_mandatory_tags_sub[0].id

  depends_on = [azurerm_role_assignment.add_g2s_mandatory_tags_role_sub]
}

# --- Security Control and Cost Control Tags Policy ---

variable "security_cost_policy_enabled" {
  type        = bool
  description = "Enable the SecurityControl and CostControl tags auto-fill policy."
  default     = true
}

resource "azurerm_policy_definition" "add_security_cost_tags" {
  name         = "add-security-cost-control-tags"
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

resource "azurerm_resource_group_policy_assignment" "add_security_cost_tags_rg" {
  count                = var.security_cost_policy_enabled && var.tag_policy_scope == "resource_group" ? 1 : 0
  name                 = "add-security-cost-tags"
  resource_group_id    = azurerm_resource_group.rg.id
  policy_definition_id = azurerm_policy_definition.add_security_cost_tags.id
  location             = var.location

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_subscription_policy_assignment" "add_security_cost_tags_sub" {
  count                = var.security_cost_policy_enabled && var.tag_policy_scope == "subscription" ? 1 : 0
  name                 = "add-security-cost-tags"
  subscription_id      = data.azurerm_subscription.current.subscription_id
  policy_definition_id = azurerm_policy_definition.add_security_cost_tags.id
  location             = var.location

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_role_assignment" "add_security_cost_tags_role_rg" {
  count = var.security_cost_policy_enabled && var.tag_policy_scope == "resource_group" ? 1 : 0

  scope              = local.tag_policy_rg_scope_id
  role_definition_id = "/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c"
  principal_id       = azurerm_resource_group_policy_assignment.add_security_cost_tags_rg[0].identity[0].principal_id
}

resource "azurerm_role_assignment" "add_security_cost_tags_role_sub" {
  count = var.security_cost_policy_enabled && var.tag_policy_scope == "subscription" ? 1 : 0

  scope              = local.tag_policy_sub_scope_id
  role_definition_id = "/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c"
  principal_id       = azurerm_subscription_policy_assignment.add_security_cost_tags_sub[0].identity[0].principal_id
}

resource "azurerm_resource_group_policy_remediation" "add_security_cost_tags_rg" {
  count = var.security_cost_policy_enabled && var.tag_policy_scope == "resource_group" ? 1 : 0

  name                 = "remediate-security-cost-tags"
  resource_group_id    = azurerm_resource_group.rg.id
  policy_assignment_id = azurerm_resource_group_policy_assignment.add_security_cost_tags_rg[0].id

  depends_on = [azurerm_role_assignment.add_security_cost_tags_role_rg]
}

resource "azurerm_subscription_policy_remediation" "add_security_cost_tags_sub" {
  count = var.security_cost_policy_enabled && var.tag_policy_scope == "subscription" ? 1 : 0

  name                 = "remediate-security-cost-tags"
  subscription_id      = data.azurerm_subscription.current.subscription_id
  policy_assignment_id = azurerm_subscription_policy_assignment.add_security_cost_tags_sub[0].id

  depends_on = [azurerm_role_assignment.add_security_cost_tags_role_sub]
}
