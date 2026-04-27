# UnifiedCare API — Auth & Headers

## Base URL
```
DEV:  https://dev-uc.ihealth-eng.com/v1/uc
PROD: https://uc-prod.ihealth-eng.com/v1/uc
```

## Required Headers (every request)
```http
x-session-token: <JWT>
Content-Type: application/json
Accept: application/json, text/plain, */*
Origin: https://ucfe-dev.ihealth-eng.com
Referer: https://ucfe-dev.ihealth-eng.com/
```

## Getting the Session Token

### Option A — Env var (preferred for scripts)
```bash
export UC_SESSION_TOKEN="eyJ0eXAi..."
python3 uc_client.py my-patients
```

### Option B — Auto-extract from running Chrome (uc_client.py does this automatically)
`uc_client.py` uses Puppeteer to intercept a lightweight request from the already-open browser
and pull the `x-session-token` header. No manual steps needed as long as the DEV portal is open
in Chrome.

### Option C — Manual extraction
1. Open DEV portal in Chrome → DevTools → Network tab
2. Filter by `dev-uc.ihealth-eng.com`
3. Copy the `x-session-token` header value from any request
4. Export: `export UC_SESSION_TOKEN="<value>"`

### Option D — Login API
```bash
curl -X POST https://dev-uc.ihealth-eng.com/v1/uc/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"<email>","password":"<password>"}'
```
Response contains `data.token` → use as `x-session-token`.

### Token refresh
```
GET /v1/uc/auth/refresh-token
```
Returns a new JWT in `data.sessionToken` (not `data.token`). Works on both dev and prod. Call when you get 401 responses.

## Current Session
- **User ID**: `65bbcee3316c7e2fc37b3688`
- **Email**: `thong.le2@ihealthlabs.com`
- **User type**: EMPLOYEE
- Tokens expire ~24h. If requests return 401, re-extract from browser.

## Org / Clinic IDs (DEV)
- **Clinic 1212**: `1212 Leandro Family Health Demo Associates`
- Use `GET /v1/uc/auth/me` to get current user's org assignments after login.

## Common Error Codes
| Code | Meaning | Fix |
|------|---------|-----|
| 401  | Token expired/invalid | Re-extract token |
| 403  | No permission for resource | Check role assignments |
| 404  | Resource not found | Check memberId / path |
| 422  | Validation error | Check request body fields |
