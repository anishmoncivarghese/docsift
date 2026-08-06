# DocSift in Power Automate

A flow that uploads a document, waits for conversion, and returns the search
results — the polling wrapper a Copilot Studio action cannot do on its own.

## Prerequisite

The custom connector from `../copilot-studio/README.md`. Create it once; both
Power Automate and Copilot Studio use the same connector.

## Flow shape

1. **Trigger** — whatever suits you: *When a file is created* in SharePoint or
   OneDrive, a manual trigger, or *When Copilot Studio calls a flow*.

2. **DocSift — uploadDocument**
   - `file`: the file content from the trigger.
   - `engine`: leave as `auto`.
   - Outputs: `job_id`, `document_id`.

3. **Initialize variable** — name `jobStatus`, type String, value `queued`.

4. **Do until** — condition: `jobStatus` **is equal to** `succeeded`.
   Set *Limits* to a count of 60 and a timeout of `PT30M`, so a slow document
   does not spin forever.
   Inside the loop:
   - **Delay** — 5 seconds. (Without this the loop burns its iteration count in
     seconds and gives up before conversion finishes.)
   - **DocSift — getJobStatus** with `job_id` from step 2.
   - **Set variable** `jobStatus` to the `status` output.
   - **Condition** — if `jobStatus` is equal to `failed`, **Terminate** the flow
     as Failed with the job's `error` value. Without this the loop runs to its
     limit on a failed conversion.

5. **DocSift — searchDocument**
   - `document_id`: from step 2.
   - `q`: your query.
   - `limit`: 5. `max_tokens`: 5000.

6. **Respond** — return the `results` array. Each entry carries `text`,
   `section_path`, `pages` and `score`, which is enough to answer with citations.

## Why the loop

Conversion runs in the background. `uploadDocument` returning does not mean the
document is ready — it means it is queued. A flow that fetches the result
immediately after uploading will get a 404 or an unfinished job on any document
large enough to matter.
