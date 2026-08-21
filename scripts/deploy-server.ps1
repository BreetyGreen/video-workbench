param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_.@-]+$')]
    [string]$SshTarget,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^/[A-Za-z0-9_./-]+$')]
    [string]$RemotePath
)

$ErrorActionPreference = 'Stop'

if ($RemotePath -eq '/' -or $RemotePath.Length -lt 5) {
    throw 'RemotePath must be a dedicated absolute project directory, not root.'
}

& ssh $SshTarget "test -d '$RemotePath' && test -f '$RemotePath/deploy/compose.yml' && test -f '$RemotePath/.env.production'"
if ($LASTEXITCODE -ne 0) {
    throw 'Remote project or .env.production is missing. Clone/copy the project and create the protected environment file first.'
}

& ssh $SshTarget "cd '$RemotePath' && docker compose --env-file .env.production -f deploy/compose.yml -f deploy/compose.production.yml config >/dev/null && docker compose --env-file .env.production -f deploy/compose.yml -f deploy/compose.production.yml up -d --build && docker compose --env-file .env.production -f deploy/compose.yml -f deploy/compose.production.yml ps"
if ($LASTEXITCODE -ne 0) {
    throw "Remote deployment failed with exit code $LASTEXITCODE"
}
