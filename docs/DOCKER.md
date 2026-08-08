# Running DocSift in Docker

The image is built and smoke-tested in CI: every build starts the container,
converts a real PDF end to end and checks the Markdown is non-empty before the
image is pushed. It carries **both** conversion engines, because routing sends
every PDF to Docling with no fallback -- an API-only image would fail on the
format the service exists for.

    docker build -t docsift .
    docker run -p 8000:8000 -v docsift-data:/data docsift

That uses a named volume (`docsift-data`) for `/data`, where the SQLite
database and stored documents live.

Carrying both engines makes the image large. Docling's model weights are baked
in at build time rather than downloaded on first use, so the first conversion
after a deploy is not a multi-minute stall and the running container needs no
outbound access to Hugging Face. Torch is pinned to the CPU wheels; the default
Linux build bundles CUDA runtimes a CPU container will never execute.

Expect a slow first build (model download) and a multi-gigabyte image.

**Use a named volume, not a bare host bind mount.** The container runs as
uid 10001, not root. A named volume like the example above is created
owned by that user automatically. A host bind mount

    docker run -p 8000:8000 -v /host/path:/data docsift   # will not start

arrives **root-owned**, so uid 10001 cannot create the database file and the
container fails on its first request. If you need a bind mount for a
specific host path, `chown 10001:10001 /host/path` first:

    sudo chown 10001:10001 /host/path
    docker run -p 8000:8000 -v /host/path:/data docsift

The image publishes a `HEALTHCHECK` against `/health` and declares `/data`
as a volume.

For a hosted deployment, see [DEPLOY_AZURE.md](DEPLOY_AZURE.md).
