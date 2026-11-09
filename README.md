# task-flow-backend
todo list app backend
# Backend authentication

The browser auth flow uses JWTs in `HttpOnly` cookies. The access token is sent
automatically with API requests, and JavaScript cannot read either token. Login
and registration therefore return an empty `refresh` field in JSON; the real
refresh token is stored in the `refresh_token` cookie.

## Browser request flow

1. Make `GET /api/v1/auth/csrf/` with `credentials: 'include'` and read the
   returned `csrfToken`.
2. Send that value as the `X-CSRFToken` header when registering, logging in,
   refreshing tokens, logging out, or making any other state-changing request.
   Include `credentials: 'include'` on all requests so the browser sends cookies.
3. If registration or login changes the CSRF cookie, request a fresh token from
   `/api/v1/auth/csrf/` before the next state-changing request.

For example:

```js
const csrfResponse = await fetch(`${apiUrl}/api/v1/auth/csrf/`, {
  credentials: 'include',
})
const { csrfToken } = await csrfResponse.json()

const response = await fetch(`${apiUrl}/api/v1/auth/login/`, {
  method: 'POST',
  credentials: 'include',
  headers: {
    'Content-Type': 'application/json',
    'X-CSRFToken': csrfToken,
  },
  body: JSON.stringify({ email, password }),
})
```

The refresh endpoint is `POST /api/v1/auth/token/refresh/`. The refresh cookie
is rotated and the old token is blacklisted. Logout is
`POST /api/v1/auth/logout/`; it clears the cookies and blacklists the refresh
token.

## Deployment configuration

Set a randomly generated `DJANGO_SECRET_KEY` of at least 50 characters,
`DJANGO_DEBUG=False`, `ALLOWED_HOSTS`,
`CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` in the deployment
environment. Provide PostgreSQL credentials through `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_HOST`, and `DB_PORT`. Configure a production
`EMAIL_BACKEND` for password resets and email verification. The local defaults
allow only the Vite development origins and use the console email backend.
Run `python manage.py migrate` after enabling the JWT blacklist app so token
rotation and logout can revoke refresh tokens.

JWT cookies are `Secure` by default outside debug mode. For a frontend hosted
on a different site, configure `JWT_AUTH_SAMESITE=None` and use HTTPS; the
browser and server must still be configured to allow credentialed requests only
from the intended frontend origin. HTTPS redirection is enabled outside debug
mode; if TLS terminates at a reverse proxy, configure that proxy to forward the
scheme correctly. Set `SECURE_HSTS_SECONDS` only after confirming the whole
site is HTTPS-only. Enable `SECURE_HSTS_INCLUDE_SUBDOMAINS` or
`SECURE_HSTS_PRELOAD` only if all affected domains are permanently HTTPS-only.
Email verification is currently optional and can be made mandatory with the
allauth setting if that matches the product's signup policy.