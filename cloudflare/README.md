# Cloudflare package

Serves the built frontend and routes `/api/*` to the Python Container. Generated scenarios and local colour scales use the private `draincheck-state` R2 bucket.

Follow the [hosting guide](../docs/CLOUDFLARE_DEPLOYMENT.md) for real-data preparation, account configuration, Docker requirements, deployment and verification.

With Node 22+, run inside this directory:

```sh
pnpm install --ignore-workspace --frozen-lockfile --ignore-scripts
pnpm --ignore-workspace check
pnpm --ignore-workspace test
pnpm --ignore-workspace dry-run
```

Build the parent frontend first. Dry-run validates Worker configuration only; it does not build or deploy the Container.
