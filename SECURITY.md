# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Instead, use
GitHub's private reporting: **Security → Report a vulnerability** on this
repository. You'll get a response within a few days.

## Security model (what the server guarantees)

- **API keys**: remote users send provider keys in HTTP headers
  (`X-Provider-API-Key`), never in tool arguments — so keys stay out of model
  transcripts and logs. Keys are passed directly to the provider client, are
  hidden from `repr()`/logging, and are never written to the environment.
  With `BYOK_ONLY=true`, the server's own keys are never used for requests.
- **GitHub tokens**: tokens are only ever attached to `github.com` clone URLs
  (never to other hosts), and the server's own `GITHUB_TOKEN` is never used
  on behalf of remote callers — they must supply their own.
- **SSRF**: repository URLs must be HTTPS and must not resolve to private,
  loopback, link-local, or otherwise reserved address space. DNS-rebinding
  protection is enabled on the HTTP transports.
- **Filesystem**: hosted deployments refuse the local-filesystem tools unless
  the operator opts in via `LOCAL_ROOT` (both `path` and `output_dir` are then
  sandboxed to it), and repo documentation is written to per-request temp
  directories that are deleted after the run.
- **Abuse limits**: per-client rate limiting, bounded pipeline concurrency,
  pipeline timeout, repository size cap, and per-file size cap.

## Supported versions

Only the latest released version receives security fixes.
