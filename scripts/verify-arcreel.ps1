$ErrorActionPreference = 'Stop'

$healthUri = 'http://127.0.0.1:1241/health'
$homeUri = 'http://127.0.0.1:1241/'

$health = Invoke-WebRequest -UseBasicParsing -Uri $healthUri -TimeoutSec 10
if ($health.StatusCode -ne 200) {
    throw "ArcReel health check returned HTTP $($health.StatusCode)"
}

$homepageResponse = Invoke-WebRequest -UseBasicParsing -Uri $homeUri -TimeoutSec 10
if ($homepageResponse.StatusCode -ne 200) {
    throw "ArcReel home page returned HTTP $($homepageResponse.StatusCode)"
}

[pscustomobject]@{
    Service = 'ArcReel'
    HealthStatus = $health.StatusCode
    HomeStatus = $homepageResponse.StatusCode
    HealthUri = $healthUri
    HomeUri = $homeUri
} | Format-List
