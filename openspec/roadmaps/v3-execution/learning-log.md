# Learning Log

| Item | Status | Summary |
|------|--------|--------|
| X3 | implementation | Removed from pyproject entirely; external invocation documented in evaluation/RE |
| P21 | implementation | _run_blocking: asyncio.run when no loop; single-worker-thread asyncio.run when i |
| P24 | review | All accepted; verdict 6 pins legacy as_*_tools() shim removal as P17 exit criter |
| P19 | review | Deleted harnesses.<h>.model + StaticModelProvider pre-users (Churn Rule: breakin |
| P10 | review | hasattr-discovery + ExtensionBase no-op defaults preserves structural compat for |
| P27 | review | Per-source FastAPI mock apps expose /openapi.json; existing http_tools discovery |
| P13 | review | Never os.environ; empty value masks process env; ~30-line parser, no python-dote |
| P7 | review | ConsumerModelProvider rewrites ModelRequest.consumer to the job binding (default |
| P6 | review | In-memory SessionRegistry is the first consumer of the P24 session-registry cont |
