# Deploying DocSift to Azure Container Apps

This is the deployment that makes the Power Platform custom connector callable:
Container Apps gives you an HTTPS endpoint with a certificate, which is what a
connector requires — Azure Container Instances only hands out plain HTTP.

You do **not** need Docker installed. `az acr build` builds the image inside
Azure from the `Dockerfile` in this repo.

## Before you start

    brew install azure-cli
    az login

Then pick names. `ACR` and `APP` become part of public DNS names, so they must
be globally unique and lowercase.

    RG=docsift-rg
    LOC=eastus
    ACR=docsiftacr$RANDOM
    ENVNAME=docsift-env
    APP=docsift

## 1. Resource group and registry

    az group create -n $RG -l $LOC
    az acr create -g $RG -n $ACR --sku Basic --admin-enabled true

## 2. Build the image in Azure

Run this from the repository root:

    az acr build -r $ACR -t docsift:0.4.0 .

Expect this to take a while and to produce a multi-gigabyte image. The build
installs both conversion engines and bakes Docling's model weights into the
image so the first conversion after a deploy isn't a multi-minute stall.

**This is the first time the Dockerfile has ever been built.** If it fails, the
error is a genuine finding, not a misconfiguration on your end — send it over.

## 3. Container Apps environment

    az extension add --name containerapp --upgrade
    az provider register -n Microsoft.App --wait
    az provider register -n Microsoft.OperationalInsights --wait

    az containerapp env create -g $RG -n $ENVNAME -l $LOC

## 4. Deploy

Generate an API key first — this is your secret, so create it yourself and keep
it somewhere safe:

    openssl rand -hex 32

Then deploy, pasting that value in place of `PASTE_KEY_HERE`:

    ACR_PASSWORD=$(az acr credential show -n $ACR --query "passwords[0].value" -o tsv)

    az containerapp create \
      -g $RG -n $APP --environment $ENVNAME \
      --image $ACR.azurecr.io/docsift:0.4.0 \
      --registry-server $ACR.azurecr.io \
      --registry-username $ACR \
      --registry-password "$ACR_PASSWORD" \
      --target-port 8000 --ingress external \
      --cpu 2 --memory 4Gi \
      --min-replicas 1 --max-replicas 1 \
      --secrets docsift-api-key=PASTE_KEY_HERE \
      --env-vars DOCSIFT_API_KEY=secretref:docsift-api-key

### Why `--min-replicas 1 --max-replicas 1` is not optional

- **Min 1.** Conversions run on an in-process thread pool. If the app scales to
  zero between the upload call and the status poll, every in-flight job dies
  silently.
- **Max 1.** The job registry lives in process memory, and documents and the
  database are local files. A second replica cannot see documents uploaded to
  the first — uploads and searches would land on different instances at random.

This is a documented single-process design. Do not "fix" it by scaling out.

## 5. Point the app at its own URL

The connector document needs the public hostname, which only exists after the
app does:

    FQDN=$(az containerapp show -g $RG -n $APP --query properties.configuration.ingress.fqdn -o tsv)
    echo "https://$FQDN"

    az containerapp update -g $RG -n $APP \
      --set-env-vars DOCSIFT_PUBLIC_URL=https://$FQDN

## 6. Check it is alive

    curl https://$FQDN/health
    curl https://$FQDN/version

`/health` and `/version` are deliberately open. Every `/v1/*` route requires the
`X-API-Key` header:

    curl -H "X-API-Key: YOUR_KEY" -F "file=@some.pdf" https://$FQDN/v1/documents

That should return `202` with a job id. Poll `/v1/jobs/{job_id}` until it reports
`succeeded` — the first PDF is the real test of whether the baked-in Docling
models work.

## 7. Regenerate the connector file

    DOCSIFT_PUBLIC_URL=https://$FQDN docsift openapi --format swagger2 -o docsift-connector.json

Re-import that in Power Apps (or just edit **Host** on the existing connector's
General tab), create a connection with your API key, and run **Test** on
`searchDocument`.

---

## On persistence

The steps above use **ephemeral storage**: a restart or a redeploy loses
converted documents and the database. For finishing connector verification that
is fine, and it keeps the deployment to a single resource.

Mounting an Azure Files share for `/data` is the obvious next step, and it comes
with a real caveat worth knowing before you rely on it: **SQLite over an SMB
file share is a known-bad combination.** Network file locking is where SQLite
corruption and `database is locked` errors come from. If DocSift needs durable
storage, the safer shapes are a VM with a local disk, or Container Apps with an
NFS (Premium FileStorage) mount — not the default Azure Files SMB mount.

Treat durable hosting as a design decision to make deliberately, not a flag to
add to the deploy command.

## On exposure

This deployment authenticates with a single shared secret. There is no per-user
identity, and document IDs are content hashes shared across all callers — both
are documented limitations. Keep the URL and the key private. This is your
verification instance, not a public demo.

## Cost control

When you are done verifying, stop paying for it:

    az containerapp update -g $RG -n $APP --min-replicas 0    # keeps the app, stops the compute

Or remove everything:

    az group delete -n $RG --yes
