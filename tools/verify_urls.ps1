# Batch check URLs against local verify-source endpoint
$Endpoint = "http://127.0.0.1:8000/api/verify-source/"
$Headers = @{ "Content-Type" = "application/json" }

$Urls = @(
    "http://infowars.com/article/123?utm=abc",
    "https://www.naturalnews.com/2024/12/claim.html",
    "https://beforeitsnews.com/politics/2025/12/something-claim.html",
    "https://yournewswire.com/sensation/",
    "https://neonnettle.com/tale/story",
    "https://worldnewsdailyreport.com/health-case-999/",
    "http://abcnews.com.co/story/example",
    "https://nationalreport.net/expose/",
    "http://empirenews.net/shocking/",
    "https://newslo.com/breaking/",
    "http://huzlers.com/prank/",
    "https://civictribune.com/politics/"
)

foreach ($u in $Urls) {
    try {
        $body = @{ url = $u } | ConvertTo-Json -Compress
        $resp = Invoke-RestMethod -Uri $Endpoint -Method Post -Headers $Headers -Body $body
        $domain = $resp.domainCheck.domain
        $verdict = $resp.domainCheck.verdict
        $rep = $resp.domainCheck.reputation
        $conf = $resp.domainCheck.confidence
        Write-Host "URL: $u" -ForegroundColor Cyan
        Write-Host "  Domain: $domain  | Reputation: $rep  | Verdict: $verdict  | Confidence: $conf" -ForegroundColor Green
    } catch {
        Write-Host "URL: $u" -ForegroundColor Cyan
        Write-Host "  Error: $($_.Exception.Message)" -ForegroundColor Red
    }
}
