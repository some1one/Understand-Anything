# Dockerfile Language Prompt Snippet

## Key Concepts

- **Multi-Stage Builds**: Multiple `FROM` statements to separate build and runtime stages, reducing image size
- **Layer Caching**: Filesystem-changing instructions create image layers; instruction order and inputs affect cache reuse
- **Base Images**: `FROM image:tag` or a digest selects the base; identify the actual runtime and libc requirements
- **COPY vs ADD**: `COPY` for local files (preferred), `ADD` for URLs and tar extraction
- **Build Arguments**: `ARG` for build-time variables, `ENV` for runtime environment variables
- **Health Checks**: `HEALTHCHECK` configures Docker container health; orchestrator readiness/liveness probes are separate configuration
- **Entry Point vs CMD**: `ENTRYPOINT` sets the executable, `CMD` provides default arguments
- **User Permissions**: `USER` instruction to run as non-root for security
- **Ignore Patterns**: `.dockerignore` excludes files from the build context (like `.gitignore`)

## Notable File Patterns

- `Dockerfile` — Primary container image definition (at project root)
- `Dockerfile.dev` / `Dockerfile.prod` — Environment-specific Dockerfiles
- `docker-compose.yml` — Multi-container application orchestration
- `docker-compose.override.yml` — Local development overrides
- `.dockerignore` — Build context exclusion patterns

## Edge Patterns

- Dockerfile `deploys` the application entry point it packages (COPY/CMD target)
- docker-compose `depends_on` Dockerfile(s) it references for building
- Dockerfile `depends_on` package manifests (package.json, requirements.txt) it copies for dependency installation
- docker-compose services create `related` edges between co-deployed components

## Summary Style

> "Multi-stage Docker build producing a minimal Node.js production image with N build stages."
> "Docker Compose configuration orchestrating N services with shared networking and persistent volumes."
> "Development Dockerfile with hot-reload support and mounted source volumes."
