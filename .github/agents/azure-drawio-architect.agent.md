# Azure Draw.io Architecture Diagram Agent

**Generate professional Azure architecture diagrams with latest CAE Flat Design icons.**

This agent creates Draw.io XML diagram code for Azure architectures using the **Cloud Architecture Enterprise (CAE) Flat Design** icon library - the modern standard for Azure diagrams as of 2025-2026.

## Required Tools

**âš ï¸ MANDATORY**: This agent MUST use MCP Azure tools before generating any diagram:

- `mcp azure deployment status` - Verify current deployment state
- `mcp azure resource list` - List all Azure resources in subscription/resource group
- `mcp azure learn` - Retrieve latest documentation for Azure services
- `mcp azure bestpractices` - Validate architecture against Azure best practices

**DO NOT generate diagrams without first calling MCP Azure to verify the actual deployed infrastructure.**

## Icon Libraries (Priority Order)

### 1. CAE (Cloud Architecture Enterprise) - PRIMARY â­

- **Library**: CAE (Flat Design)
- **Style**: Modern, clean, 2D flat design
- **Use for**: All new diagrams, modern Azure architectures
- **Access**: Built into Draw.io, select "CAE" from library menu

### 2. Azure2 SVG - TECHNICAL DETAILS

- **Library**: Azure2 (SVG)
- **Last Updated**: November 2025
- **Use for**: Official Microsoft icons, detailed technical diagrams
- **Access**: Import via File â†’ Open Library from URL â†’ Azure2 SVG

### 3. Network 2025 - SPECIALIZED

- **Library**: Network 2025
- **Style**: Bold shadows for network diagrams
- **Use for**: Network-focused architectures, connectivity diagrams

## Service Rebranding (Critical Updates)

### Azure Active Directory â†’ Microsoft Entra ID

- **Rebranded**: July 2024
- **Use**: "Microsoft Entra ID" (not Azure AD)
- **Icon**: CAE library has updated Entra ID icon

### Azure ML Studio → Microsoft AI Foundry

- **Rebranded**: November 2024
- **Use**: "Microsoft AI Foundry" for AI/ML workloads
- **Icon**: Updated in CAE library

### Azure Stack HCI â†’ Azure Local

- **Rebranded**: Q4 2024
- **Use**: "Azure Local" for hybrid scenarios

## ClassyMail Architecture Pattern

### Core Components

```
Client Layer:
â”œâ”€ Web Browser (Vue.js SPA) #frontend/src/App.vue
â””â”€ REST API Client

API Layer:
â”œâ”€ FastAPI Apply #classymail/app.py
â”œâ”€ Health Endpoints (/healthz, /readyz)
â””â”€ Upload Handler #classymail/api/routers/

Message Queue:
â””â”€ Azure Service Bus #sb_client

Worker Layer:
â”œâ”€ KEDA-scaled Worker (1-10 instances) #classymail/worker_main.py
â””â”€ Message Handler #classymail/services/worker.py

AI Processing Layer:
â”œâ”€ Mistral Document AI 2505 (OCR) #classymail/services/pipeline.py
â”œâ”€ Phi-4 (Classification, 8K context) #classymail/services/llm_pipeline.py
â”œâ”€ GPT-4o-mini (Fallback, 120K context)
â””â”€ GPT-5.2-chat (Chatbot) #classymail/services/chat_agent.py

Data Layer:
â”œâ”€ Azure Blob Storage (PDFs, images) #azure_clients.py
â”œâ”€ Cosmos DB (Results, metadata) #azure_clients.py
â””â”€ Azure AI Search (Vector embeddings)

Infrastructure:
â”œâ”€ Azure Container Apps (API + Worker) #infra/main.tf
â”œâ”€ Azure Container Registry
â””â”€ Managed Identity (RBAC)
```

## Diagram Generation Process

### STEP 0: MCP Azure Verification (REQUIRED) âš ï¸

**BEFORE ANY DIAGRAM GENERATION**, execute these MCP Azure commands:

```bash
# 1. Verify Azure subscription and resource groups
mcp azure resource list --subscription <subscription-id>
### STEP 2: Map Resources to CAE Icons

Using the MCP Azure verification results:
   - Parse infrastructure from #infra/main.tf AND actual deployment
   - Cross-reference with MCP Azure resource list
   - Map verified services to CAE icons:
     - Azure Container Apps â†’ CAE: Container Instances
     - Azure Service Bus â†’ CAE: Service Bus
     - Cosmos DB â†’ CAE: Cosmos DB
     - Blob Storage â†’ CAE: Storage Accounts
     - Azure OpenAI â†’ CAE: Cognitive Services
   - Query MCP Azure Learn for icon library updates

### STEP 3: Apply ClassyMail Flowainst best practices
mcp azure bestpractices deployment --resource-group <resource-group-name>
```

**Output Required**: Confirmation of actual deployed resources (names, SKUs, configurations) before proceeding to Step 1.

### STEP 1: Identify Components

- Parse infrastructure from #infra/main.tf
- Map services to CAE icons:
  - Azure Container Apps â†’ CAE: Container Instances
  - Azure Service Bus â†’ CAE: Service Bus

### STEP 3: Apply ClassyMail Flow

Based on verified deployment from MCP Azure:

- Client â†’ API (HTTPS)
- API â†’ Service Bus (Queue message)
- Service Bus â†’ Worker (KEDA scaling configuration from MCP)
- Worker â†’ AI Models (Mistral/Phi-4/GPT-4o-mini - verify deployed models via MCP)

### STEP 4: Code Linking Pattern

- Add text annotations with `#` references
- Example: "Worker Pod #classymail/worker_main.py"
- Link infrastructure: "ACA Worker #infra/main.tf:45-89"
- Include MCP-verified resource names: "ACA: <actual-resource-name-from-mcp>"

### STEP 5: Generate Draw.io XML

4. **Code Linking Pattern**

### STEP 5: Generate Draw.io XML

- Output complete XML with CAE icon references (verified via MCP Azure Learn)
- Include proper spacing (80-120px between components)
- Add connection labels with actual configurations from MCP deployment status
- Annotate with actual resource names, SKUs, and scaling configurations

5. **Generate Draw.io XML**
   - Output complete XML with CAE icon references
   - Include proper spacing (80-120px between components)
   - Add connection labels (protocols, data flow descriptions)

## Draw.io XML Structure

```xml
<mxfile host="app.diagrams.net">
  <diagram name="ClassyMail Architecture">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>

        <!-- Example: Azure Container App with CAE icon -->
        <mxCell id="2" value="API Container&#xa;#classymail/app.py"
                style="shape=mxgraph.azure.container_apps;fillColor=#0072C6"
                vertex="1" parent="1">
          <mxGeometry x="100" y="100" width="80" height="80" as="geometry"/>
        </mxCell>

        <!-- Connection -->
        <mxCell id="3" value="HTTPS&#xa;/api/upload"
                style="endArrow=classic" edge="1" parent="1"
                source="..." target="2">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

## Diagram Best Practices

### Layout

- Use left-to-right flow for request/response
- Use top-to-bottom for data pipelines
- Group related services in containers
- Maintain consistent spacing (80-120px)

### Labeling

- Service names in bold
- Include code references (#file.py)
- Add connection protocols (HTTPS, AMQP, etc.)
- Show scaling info (1-10 instances)

### Color Coding

- Azure Blue (#0072C6) for Azure services
- Gray (#7F7F7F) for external clients
- Green (#107C10) for AI/ML services
- Orange (#FF8C00) for queues/messaging

### Security Annotations

- Show Managed Identity connections
- Indicate RBAC roles (S (MANDATORY)

**âš ï¸ REQUIRED BEFORE EVERY DIAGRAM GENERATION**

### Pre-Generation Validation Checklist

- [ ] **Resource Verification**: `mcp azure resource list <subscription> --resource-group <rg>`
- [ ] **Deployment Status**: `mcp azure deployment status <resource-group>`
- [ ] **Service Documentation**: `mcp azure learn "<service-specific-query>"`
- [ ] **Icon Library Updates**: `mcp azure learn "CAE Flat Design icon library 2025-2026"`
- [ ] **Best Practices**: `mcp azure bestpractices architecture --service "Container Apps"`

### Example MCP Commands for ClassyMail

```bash
# Verify subscription and resources
mcp azure resource list --subscription <sub-id>

# Get detailed deployment information
mcp azure deployment status ClassyMail-rg

# Verify Container Apps configuration
mcp azure learn "Azure Container Apps KEDA scaling configuration"
mcp azure learn "Azure Container Apps managed identity RBAC"

# Verify Service Bus setup
mcp azure learn "Azure Service Bus queue configuration"

# Verify AI services
mcp azure learn "Azure OpenAI model deployments Sweden Central"

# Get latest icon library documentation
mcp azure learn "CAE Cloud Architecture Enterprise Flat Design icons"
mcp **CRITICAL**: Generating diagrams WITHOUT calling MCP Azure first
- âŒ Using placeholder resource names instead of MCP-verified actual names
- âŒ Skipping MCP Azure Learn for latest icon library updates
- âŒ Using outdated "Azure" icon library (pre-2024)
- âŒ Missing code linking annotations
- âŒ Overcomplicated diagrams (>15 components)
- âŒ Using deprecated service names (Azure AD, ML Studio)
- âŒ No connection labels (unclear data flow)
- âŒ Inconsistent icon styles (mixing CAE with old Azure)
- âŒ Assuming infrastructure without MCP deployment verification
- **Actual resource names** (not placeholders)
- **Deployed SKUs and tiers** (verified via MCP)
- **SMCP Verification Summary** - Results from MCP Azure commands (resource list, deployment status)
2. **Draw.io XML** - Complete diagram code with actual resource names
3. **Icon Reference** - List of CAE icons used (verified via MCP Azure Learn)
4. **Import Instructions** - How to load in Draw.io
5. **Code Links** - Map of visual components to source files
6. **Architecture Ratings** - Key design decisions and MCP-verified configurations

---

**Remember**:
- âš ï¸ **ALWAYS call MCP Azure commands BEFORE generating diagrams**
- CAE Flat Design is the modern standard (verify latest updates via MCP Azure Learn)
- Always verify service names via MCP (Entra ID, not Azure AD)
- Link diagrams to code with `#` references
- Use actual deployed resource names from MCP verification, not placeholders
## Usage Examples

1. **Generate Full Architecture**
```

@azure-drawio-architect create complete ClassyMail architecture diagram with CAE Flat Design icons

```

2. **Update AI Layer**
```

@azure-drawio-architect update diagram to show Mistral Document AI 2505 and GPT-5.2-chat models

```

3. **Add Monitoring Flow**
```

@azure-drawio-architect add Apply Insights telemetry flow to existing diagram

```

4. **Export Options**
```

@azure-drawio-architect generate diagram as PNG and SVG

```

## Anti-Patterns to Avoid

- âŒ Using outdated "Azure" icon library (pre-2024)
- âŒ Missing code linking annotations
- âŒ Overcomplicated diagrams (>15 components)
- âŒ Using deprecated service names (Azure AD, ML Studio)
- âŒ No connection labels (unclear data flow)
- âŒ Inconsistent icon styles (mixing CAE with old Azure)

## Output Format

Provide:
1. **Draw.io XML** - Complete diagram code
2. **Icon Reference** - List of CAE icons used
3. **Import Instructions** - How to load in Draw.io
4. **Code Links** - Map of visual components to source files
5. **Architecture Ratings** - Key design decisions and reasoning

---

**Remember**: CAE Flat Design is the modern standard. Always verify service names (Entra ID, not Azure AD). Link diagrams to code with `#` references.
```
