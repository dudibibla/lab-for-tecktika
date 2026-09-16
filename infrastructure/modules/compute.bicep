@description('Base name used to derive compute resource names.')
param baseName string

@description('Deployment environment name exposed to the backend runtime.')
param environmentName string

@description('Azure region for compute resources.')
param location string = resourceGroup().location

@description('Azure region for the Static Web App. Static Web Apps only deploys to a short fixed list of regions (centralus, eastus2, westus2, westeurope, eastasia as of writing), which often does not include the region used for everything else.')
param staticWebAppLocation string = 'eastus2'

@description('Tags applied to all resources in this module.')
param tags object = {}

@description('Log Analytics workspace resource ID backing the Container Apps environment.')
param logAnalyticsWorkspaceId string

@description('Application Insights connection string, wired into both the backend and the worker.')
@secure()
param appInsightsConnectionString string

@description('Storage account name backing the queue/table/blob and the Function App runtime.')
param storageAccountName string

@description('Blob container name holding the source-of-truth PDFs.')
param blobContainerName string

@description('Blob container name that receives uploads before the Worker copies them into the primary container.')
param stagingContainerName string

@description('Queue name the backend enqueues ingestion/deletion jobs to and the worker consumes from.')
param queueName string

@description('Table name tracking per-file job status.')
param jobStatusTableName string

@description('Azure AI Search endpoint.')
param searchEndpoint string

@description('Azure OpenAI endpoint.')
param openAiEndpoint string

@description('Azure OpenAI chat deployment name.')
param chatDeploymentName string

@description('Azure OpenAI embedding deployment name.')
param embeddingDeploymentName string

@description('Document Intelligence (multi-service Cognitive Services) endpoint, used by the worker to attach DocumentIntelligenceLayoutSkill billing to the search skillset.')
param documentIntelligenceEndpoint string

@description('Placeholder container image for the backend Container App. CI/CD replaces this with the built image after the first deploy.')
param backendContainerImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('GHCR username for pulling the backend image. Only needed when the package is private - leave empty for a public package (anonymous pull).')
param ghcrUsername string = ''

@description('GHCR PAT (read:packages) for pulling the backend image. Only needed when the package is private.')
@secure()
param ghcrPassword string = ''

@description('Origins allowed to call the backend API cross-origin (the frontend\'s own hostname). Empty disables CORS on the backend.')
param backendCorsAllowedOrigins array = []

@description('Entra ID tenant ID used for backend token validation.')
param entraTenantId string = ''

@description('Entra ID API/app registration client ID exposed by the backend.')
param entraApiClientId string = ''

// --- Backend: Azure Container Apps -----------------------------------------

// Container Apps caps names at 32 chars total; 'ca-backend-' alone is 11, so
// baseName must be truncated here specifically (other resource types in this
// file have far higher limits and use baseName untruncated).
var containerAppNameSuffix = substring(baseName, 0, min(21, length(baseName)))

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${baseName}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: reference(logAnalyticsWorkspaceId, '2023-09-01').customerId
        sharedKey: listKeys(logAnalyticsWorkspaceId, '2023-09-01').primarySharedKey
      }
    }
  }
}

resource backendApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-backend-${containerAppNameSuffix}'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      activeRevisionsMode: 'Single'
      secrets: concat(
        [{ name: 'appinsights-connection-string', value: appInsightsConnectionString }],
        empty(ghcrPassword) ? [] : [{ name: 'ghcr-pat', value: ghcrPassword }]
      )
      // GHCR packages linked to a repo don't reliably go public even when the
      // UI says they do (observed live 2026-09-16, ghcr.io itself kept
      // rejecting anonymous pulls); pulling with an explicit credential works
      // regardless of the package's visibility state.
      registries: empty(ghcrPassword) ? [] : [
        { server: 'ghcr.io', username: ghcrUsername, passwordSecretRef: 'ghcr-pat' }
      ]
    }
    template: {
      containers: [
        {
          name: 'backend'
          image: backendContainerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'ENVIRONMENT', value: environmentName }
            { name: 'ALLOW_LOCAL_AUTH_BYPASS', value: 'false' }
            { name: 'AZURE_STORAGE_ACCOUNT_NAME', value: storageAccountName }
            { name: 'BLOB_CONTAINER_NAME', value: blobContainerName }
            { name: 'STORAGE_QUEUE_NAME', value: queueName }
            { name: 'JOB_STATUS_TABLE_NAME', value: jobStatusTableName }
            { name: 'AZURE_SEARCH_ENDPOINT', value: searchEndpoint }
            { name: 'AZURE_OPENAI_ENDPOINT', value: openAiEndpoint }
            { name: 'OPENAI_CHAT_DEPLOYMENT', value: chatDeploymentName }
            { name: 'OPENAI_EMBEDDING_DEPLOYMENT', value: embeddingDeploymentName }
            { name: 'AZURE_TENANT_ID', value: entraTenantId }
            { name: 'AZURE_CLIENT_ID_API', value: entraApiClientId }
            { name: 'CORS_ALLOWED_ORIGINS', value: join(backendCorsAllowedOrigins, ',') }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights-connection-string' }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
      }
    }
  }
}

// --- Worker: Azure Functions (Python, Linux, Consumption) -------------------

resource functionPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'plan-worker-${baseName}'
  location: location
  tags: tags
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  kind: 'functionapp'
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: 'func-worker-${baseName}'
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: functionPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      appSettings: [
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AzureWebJobsStorage__accountName', value: storageAccountName }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'STORAGE_CONNECTION__accountName', value: storageAccountName }
        { name: 'STORAGE_CONNECTION__credential', value: 'managedidentity' }
        { name: 'AZURE_STORAGE_ACCOUNT_NAME', value: storageAccountName }
        { name: 'BLOB_CONTAINER_NAME', value: blobContainerName }
        { name: 'STAGING_CONTAINER_NAME', value: stagingContainerName }
        { name: 'STORAGE_QUEUE_NAME', value: queueName }
        { name: 'JOB_STATUS_TABLE_NAME', value: jobStatusTableName }
        { name: 'AZURE_SEARCH_ENDPOINT', value: searchEndpoint }
        { name: 'AZURE_OPENAI_ENDPOINT', value: openAiEndpoint }
        { name: 'OPENAI_EMBEDDING_DEPLOYMENT', value: embeddingDeploymentName }
        { name: 'DOCUMENT_INTELLIGENCE_ENDPOINT', value: documentIntelligenceEndpoint }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
      ]
    }
  }
}

// --- Frontend: Azure Static Web Apps (Free tier) -----------------------------

resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' = {
  name: 'swa-frontend-${baseName}'
  location: staticWebAppLocation
  tags: tags
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    provider: 'None'
  }
}

output containerAppsEnvironmentId string = containerAppsEnvironment.id
output backendAppName string = backendApp.name
output backendAppPrincipalId string = backendApp.identity.principalId
output backendFqdn string = backendApp.properties.configuration.ingress.fqdn
output functionAppName string = functionApp.name
output functionAppPrincipalId string = functionApp.identity.principalId
output staticWebAppName string = staticWebApp.name
output staticWebAppDefaultHostname string = staticWebApp.properties.defaultHostname
// Deployment token is intentionally not exposed here; fetch it post-deploy with
// `az staticwebapp secrets list --name <staticWebAppName> --query properties.apiKey`
// so it never lands in ARM deployment history.
