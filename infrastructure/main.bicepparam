using 'main.bicep'

param projectName = 'ragpoc'
param environmentName = 'dev'
param location = 'swedencentral'
param openAiLocation = 'swedencentral'

param blobContainerName = 'pdf-library'
param stagingContainerName = 'staging'
param queueName = 'index-jobs'
param jobStatusTableName = 'jobstatus'

// Frontend origins allowed to PUT/GET directly against the staging container.
// Static Web App hostname from infrastructure/scripts/.generated.env (STATIC_WEB_APP_HOSTNAME).
param stagingCorsAllowedOrigins = [
  'http://localhost:5173'
  'https://delightful-river-0f09b360f.5.azurestaticapps.net'
]

// Same origins, for the backend's own CORS policy (browser calls to the API directly).
param backendCorsAllowedOrigins = [
  'http://localhost:5173'
  'https://delightful-river-0f09b360f.5.azurestaticapps.net'
]

// 'free' has no cost but caps you at 3 indexes / 50MB and no semantic ranking.
// 'basic' is the minimum tier this project is designed against.
param searchSkuName = 'basic'

// ci-backend.yml pushes both `:<sha>` and `:latest` to this public GHCR package on
// every merge to main. Pinned to `:latest` here (rather than left as the quickstart
// placeholder) so an infra-only redeploy converges the Container App back onto the
// real image instead of reverting it to the placeholder.
//
// Repo moved to dudibibla/lab-for-tecktika after the davidkorenblit GitHub
// account was blocked - ghcr.io/davidkorenblit/lab-for-tecktika-backend is no
// longer pullable at all (not just un-buildable), which fails every infra
// redeploy outright ("DENIED: requested access to the resource is denied").
param backendContainerImage = 'ghcr.io/dudibibla/lab-for-tecktika-backend:latest'

// The lab-for-tecktika-backend GHCR package doesn't reliably stay pullable
// anonymously even when its visibility is set to Public (observed live
// 2026-09-16 - ghcr.io kept returning 401/403 to anonymous pulls regardless).
// ghcrPassword (a PAT with read:packages, owned by this account) is supplied
// at deploy time via deploy-infra.yml from the GHCR_PAT repo secret, not
// hardcoded here.
param ghcrUsername = 'dudibibla'

// From register-entra-app.sh (Entra ID App Registration for user sign-in).
param entraTenantId = '6fc8a795-8bcb-4e52-8b36-41c1971e6816'
param entraApiClientId = '7267f8e7-50eb-4247-88b7-da2cc3adf6f6'
