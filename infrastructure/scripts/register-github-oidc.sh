#!/usr/bin/env bash
# Registers (or reuses) the Entra ID App Registration that GitHub Actions uses to
# deploy infrastructure via OIDC federated credentials — no client secret is ever
# generated or stored. This is separate from register-entra-app.sh, which handles
# end-user sign-in; this app exists purely so deploy-infra.yml can log in as itself.
#
# Usage:
#   ./register-github-oidc.sh <github-owner/repo> <resource-group-name> [location] [environment-name]
#
# Example:
#   ./register-github-oidc.sh davidkorenblit/lab-for-tecktika rg-ragpoc-dev swedencentral dev
set -euo pipefail

# On Git-Bash/MSYS (Windows), any argument starting with "/" — like the
# "/subscriptions/<id>/resourceGroups/<rg>" scope below — gets silently
# rewritten to a Windows path (e.g. "C:/Program Files/Git/subscriptions/...")
# before az.exe ever sees it, since MSYS assumes it's a filesystem path meant
# for the native binary being invoked. That corrupted scope is what az's API
# call reports back as "MissingSubscription". This opts out of that rewriting;
# it's a no-op on real POSIX shells (macOS/Linux CI runners, WSL).
export MSYS_NO_PATHCONV=1

GITHUB_REPO="${1:?Usage: register-github-oidc.sh <github-owner/repo> <resource-group-name> [location] [environment-name]}"
RESOURCE_GROUP="${2:?Usage: register-github-oidc.sh <github-owner/repo> <resource-group-name> [location] [environment-name]}"
LOCATION="${3:-swedencentral}"
GH_ENVIRONMENT="${4:-dev}"
APP_DISPLAY_NAME="gha-oidc-$(echo "$RESOURCE_GROUP" | tr '[:upper:]' '[:lower:]')"

echo "==> Ensuring resource group '$RESOURCE_GROUP' exists in $LOCATION"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

# Azure CLI on Windows emits CRLF even for -o tsv; `tr -d '\r'` strips the
# stray carriage return that `$(...)` command substitution otherwise leaves
# embedded at the end of the captured value (bash only trims the \n).
EXISTING_APP_ID=$(az ad app list --display-name "$APP_DISPLAY_NAME" --query "[0].appId" -o tsv | tr -d '\r')

if [ -n "$EXISTING_APP_ID" ]; then
  echo "==> Reusing existing app registration '$APP_DISPLAY_NAME' ($EXISTING_APP_ID)"
  APP_ID="$EXISTING_APP_ID"
else
  echo "==> Creating app registration '$APP_DISPLAY_NAME'"
  APP_ID=$(az ad app create --display-name "$APP_DISPLAY_NAME" --sign-in-audience AzureADMyOrg --query appId -o tsv | tr -d '\r')
fi

# `az ad sp list --filter "appId eq ..."` can fail on some CLI/Graph API
# versions with "Unsupported or invalid query filter clause specified for
# property 'appId'". `az ad sp show --id <appId>` looks up the same service
# principal directly and sidesteps the broken filter query.
SP_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv 2>/dev/null | tr -d '\r' || true)
NEWLY_CREATED_SP=false
if [ -z "$SP_ID" ]; then
  echo "==> Creating service principal for the app"
  SP_ID=$(az ad sp create --id "$APP_ID" --query id -o tsv | tr -d '\r')
  NEWLY_CREATED_SP=true
fi

# GitHub's actual OIDC subject claim is 'repo:<owner>@<ownerId>/<repo>@<repoId>:...'
# (immutable numeric IDs, not just the slug) - using the plain slug here causes
# az/login to fail in the workflow with AADSTS700213 "No matching federated
# identity record" even though the subject looks like it should match. Resolve
# the real IDs via the GitHub API so the credential actually matches.
resolve_subject_repo() {
  local repo="$1" json result
  json=$(curl -sf "https://api.github.com/repos/${repo}") || { echo ""; return; }

  if command -v jq >/dev/null 2>&1; then
    result=$(echo "$json" | jq -r '"\(.owner.login)@\(.owner.id)/\(.name)@\(.id)"' 2>/dev/null)
    [ -n "$result" ] && { echo "$result"; return; }
  fi

  # Try both interpreter names and actually verify the output, rather than
  # trusting `command -v`: on plain Git-for-Windows setups `python3` often
  # resolves to the Microsoft Store app-execution-alias stub, which exists on
  # PATH, does nothing useful, and exits nonzero - `command -v` can't tell it
  # apart from a real interpreter, so we check the real output instead.
  local py
  for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1; then
      result=$(echo "$json" | "$py" -c "import json,sys
d=json.load(sys.stdin)
print('%s@%s/%s@%s' % (d['owner']['login'], d['owner']['id'], d['name'], d['id']))" 2>/dev/null)
      [ -n "$result" ] && { echo "$result"; return; }
    fi
  done

  echo ""
}

echo "==> Resolving GitHub's immutable owner/repo IDs for the OIDC subject"
SUBJECT_REPO=$(resolve_subject_repo "$GITHUB_REPO")
if [ -n "$SUBJECT_REPO" ]; then
  echo "    using: $SUBJECT_REPO"
else
  echo "    WARNING: could not resolve owner/repo IDs (rate-limited, private repo needing auth, or no jq/python available)."
  echo "    Falling back to the plain slug '$GITHUB_REPO'. If the workflow later fails with AADSTS700213 'No"
  echo "    matching federated identity record', GitHub is asserting the owner@id/repo@id form instead - re-run"
  echo "    this script once jq/python is available, or update the federated credential subject in Entra ID"
  echo "    manually to match whatever subject that error message reports."
  SUBJECT_REPO="$GITHUB_REPO"
fi

echo "==> Configuring federated credentials for $GITHUB_REPO"

# Creates a federated credential, treating "already exists" as success and any
# other error as a real failure that aborts the script (rather than a bare
# `|| echo` that would mis-report a genuine error as a harmless duplicate).
create_federated_credential() {
  local name="$1" subject="$2"
  output=$(az ad app federated-credential create --id "$APP_ID" --parameters "{
    \"name\": \"${name}\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"${subject}\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }" 2>&1) && { echo "    created: $name"; return 0; }
  if echo "$output" | grep -qi "already exists"; then
    echo "    already exists: $name"
    return 0
  fi
  echo "ERROR: failed to create federated credential '$name':" >&2
  echo "$output" >&2
  exit 1
}

# Matches deploy-infra.yml's `environment: dev` job setting — GitHub issues the OIDC
# token with an environment-scoped subject whenever a job declares `environment:`,
# regardless of which branch or trigger fired it.
create_federated_credential "gh-environment-${GH_ENVIRONMENT}" "repo:${SUBJECT_REPO}:environment:${GH_ENVIRONMENT}"

# Fallback credential in case the `environment:` block is ever removed from the
# workflow, so plain pushes to main keep working without re-running this script.
create_federated_credential "gh-branch-main" "repo:${SUBJECT_REPO}:ref:refs/heads/main"

echo "==> Granting least-privilege roles on '$RESOURCE_GROUP' only (not the whole subscription)"
RG_ID=$(az group show --name "$RESOURCE_GROUP" --query id -o tsv | tr -d '\r')

# A service principal just created can take up to ~30-60s to replicate through
# Entra ID; assigning a role to it before that finishes fails with
# "PrincipalNotFound", which looks identical to a real error. Give it a head
# start rather than silently mis-reporting a transient failure as success.
if [ "$NEWLY_CREATED_SP" = true ]; then
  echo "    (new service principal, waiting ~20s for Entra ID replication)"
  sleep 20
fi

# Retries on PrincipalNotFound (replication lag); treats "already exists" as
# success; any other error is a real failure and aborts the script instead of
# silently claiming the role is in place.
assign_role() {
  local role="$1"
  local attempt
  for attempt in 1 2 3 4 5; do
    output=$(az role assignment create --assignee-object-id "$SP_ID" --assignee-principal-type ServicePrincipal \
      --role "$role" --scope "$RG_ID" 2>&1) && { echo "    granted: $role"; return 0; }
    if echo "$output" | grep -qi "RoleAssignmentExists"; then
      echo "    already assigned: $role"
      return 0
    fi
    if echo "$output" | grep -qi "PrincipalNotFound" && [ "$attempt" -lt 5 ]; then
      echo "    principal not yet replicated, retrying ($attempt/5)..."
      sleep 10
      continue
    fi
    echo "ERROR: failed to assign role '$role':" >&2
    echo "$output" >&2
    exit 1
  done
}

# Contributor to create/update resources...
assign_role "Contributor"

# ...plus RBAC Administrator, because role_assignments.bicep creates role assignments,
# and Contributor alone cannot grant Microsoft.Authorization/roleAssignments/write.
assign_role "Role Based Access Control Administrator"

TENANT_ID=$(az account show --query tenantId -o tsv | tr -d '\r')
SUBSCRIPTION_ID=$(az account show --query id -o tsv | tr -d '\r')

echo ""
echo "==> Done. Add these as GitHub Actions secrets on $GITHUB_REPO:"
echo "    AZURE_CLIENT_ID=$APP_ID"
echo "    AZURE_TENANT_ID=$TENANT_ID"
echo "    AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION_ID"
echo ""
echo "    Also set the repo VARIABLE (not secret) AZURE_RESOURCE_GROUP=$RESOURCE_GROUP"
echo "    (and AZURE_LOCATION=$LOCATION if you want something other than the workflow default)."
echo ""
echo "==> If you have the GitHub CLI (gh) authenticated, this does it for you:"
echo "    gh secret set AZURE_CLIENT_ID -b\"$APP_ID\" -R $GITHUB_REPO"
echo "    gh secret set AZURE_TENANT_ID -b\"$TENANT_ID\" -R $GITHUB_REPO"
echo "    gh secret set AZURE_SUBSCRIPTION_ID -b\"$SUBSCRIPTION_ID\" -R $GITHUB_REPO"
echo "    gh variable set AZURE_RESOURCE_GROUP -b\"$RESOURCE_GROUP\" -R $GITHUB_REPO"
echo "    gh variable set AZURE_LOCATION -b\"$LOCATION\" -R $GITHUB_REPO"
echo ""
echo "==> Also create a GitHub 'dev' environment (Settings > Environments) if it"
echo "    doesn't exist yet — deploy-infra.yml targets it, and the federated"
echo "    credential above is scoped to that exact environment name."
