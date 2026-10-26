# ActCheck model access

Prepared on October 26, 2026 (Asia/Almaty). This is setup documentation; no inference request has been made and no API key has been created or validated. Implementation and paid smoke tests begin on October 27 under the team plan.

## Verified configuration

| Purpose | Provider | Base URL | Model ID | Authentication |
| --- | --- | --- | --- | --- |
| Tile segmentation | Meta Model API | `https://api.meta.ai/v1` | `sam-3.1` | Bearer token |
| Agent reasoning | Baseten Model APIs | `https://inference.baseten.co/v1` | `meta-models/muse-spark-open` | Bearer token |
| Difficult scans, fallback | Meta Model API | `https://api.meta.ai/v1` | `muse-spark-1.3` | Bearer token |
| Local segmentation fallback | Hugging Face weights | Not an HTTP inference endpoint | `facebook/sam3.1` | Approved account and download token |

SAM uses `POST https://api.meta.ai/v1/responses`. Meta's official examples call the secret `MODEL_API_KEY`; this project's `.env` uses `META_API_KEY`, which the future client must explicitly pass as its API key. Spark uses the same API and authentication. [Meta SAM overview](https://dev.meta.ai/docs/sam/overview), [Meta quickstart](https://dev.meta.ai/docs/quickstart).

Baseten uses `POST https://inference.baseten.co/v1/chat/completions` with `BASETEN_API_KEY`. Its own model page and launch announcement both document the unsuffixed model ID above. The team plan's `meta-models/muse-spark-open-1026` has **not** been verified; do not configure it unless the authenticated live catalog or provider confirms it. [Baseten model page](https://www.baseten.co/library/muse-spark-open/), [Baseten launch announcement](https://www.baseten.co/resources/changelog/muse-spark-open-and-nemotron-35-super-vl-available-on-baseten/).

The `facebook/sam3.1` repository hosts checkpoints, requires sharing account information to obtain access, and points to the SAM repository for runtime instructions. Download access alone does not provide a hosted inference API. [Official SAM 3.1 model card](https://huggingface.co/facebook/sam3.1).

## Obtain and store keys

1. **Meta:** sign in to the [Meta developer dashboard](https://dev.meta.ai/), select the intended project, open API keys, and create a key. Confirm SAM 3.1 access and available hackathon credits in that account. Save the value directly as `META_API_KEY` in the ignored local `.env`; do not paste it into chat. The documented creation path is in the [Meta quickstart](https://dev.meta.ai/docs/quickstart).
2. **Baseten:** sign in to [Baseten](https://app.baseten.co/), open Organization settings → API keys, and create a personal development key or a team key with **Call Model APIs** access. Name it `actcheck-dev`; save the value immediately in `.env` as `BASETEN_API_KEY`. The provider only displays a newly created secret once. [Baseten API key instructions](https://docs.baseten.co/organization/api-keys).
3. **Local fallback:** sign in to [SAM 3.1 on Hugging Face](https://huggingface.co/facebook/sam3.1), review the access conditions, and request access. Also check [SAM 3](https://huggingface.co/facebook/sam3) if that fallback is needed. Store a download token as `HF_TOKEN` locally once available. Access approval remains an account-owner action.
4. Keep keys server-side. Commit `.env.example` with blank secret fields, never `.env`. Keep private images, responses, caches, logs, and overlays out of Git. Avoid verbose HTTP logging and shell commands that print keys.

The owner requested empty key fields and will fill them locally. No account login, access approval, key issuance, credit redemption, or authenticated access was performed in this preparation. A key being present is not proof of model access; the October 27 smoke test establishes that separately. No claim is made here that hackathon credits have been applied.

## Environment variable contract

These names are project configuration choices, except provider-documented secret names. `.env.example` and the local `.env` include the verified nonsecret defaults below; all credential fields are empty.

| Variable | Value or purpose |
| --- | --- |
| `META_API_KEY` | Meta-issued secret; explicitly pass this project's value as the Meta client's API key |
| `META_API_BASE_URL` | `https://api.meta.ai/v1` |
| `META_SAM_MODEL` | `sam-3.1` |
| `META_SPARK_MODEL` | `muse-spark-1.3` |
| `BASETEN_API_KEY` | Baseten-issued secret |
| `BASETEN_BASE_URL` | `https://inference.baseten.co/v1` |
| `BASETEN_MODEL` | `meta-models/muse-spark-open` |
| `HF_TOKEN` | Optional Hugging Face secret for approved local weights |
| `SAM_WEIGHTS_REPO` | `facebook/sam3.1` |

`META_API_KEY` is the canonical project variable. Official examples using `MODEL_API_KEY` need that name replaced or mapped when adapted on October 27. If supporting both names later, define precedence and reject conflicting values. Never silently send a Meta key to Baseten or a Baseten key to Meta.

## Integration findings and remaining checks

- **SAM request:** one user message with one short concept in `input_text` and one `input_image`; image data can be a base64 data URL. Use separate requests for tile, door, mirror, window, and bathtub. Image concept requests return every match; video and explicit object prompting have 16-object limits. These limits do not establish practical tile recall or maximum useful image resolution. [SAM prompt guide](https://dev.meta.ai/docs/sam/segmenting).
- **SAM output:** image output is a frame-zero record set with object IDs, source-pixel boxes, and base85 mask payloads. Read the per-mask encoding marker: lossless `~` and one-bit `!` are distinct. Mask raster dimensions are height then width; they need not equal source dimensions. [Output grammar](https://dev.meta.ai/docs/sam/reading-segmentation).
- **Parser:** Python `meta-sam-parser` / import `meta_sam_parser` is documented and requires Python 3.10 or later. Verify a pinned release against the first real response before relying on it. [Official client libraries](https://dev.meta.ai/docs/sam/client-libraries).
- **Agent contract:** Baseten documents tool calling and multimodal input for Muse Spark Open, but explicitly excludes it from structured outputs and JSON mode. Plan application-side JSON parsing, Pydantic validation, bounded repair retries, and a clear failure state. Do not promise deterministic responses from a seed or temperature setting. [Baseten Model APIs](https://docs.baseten.co/inference/model-apis/overview).
- **Cost:** Meta currently lists SAM at $2.50 per 1,000 images; Baseten lists Muse Spark Open at $1.25 input, $0.15 cached input, and $4.25 output per million tokens. Recheck billing before a batch; separate prompts and crops multiply image calls. These are published rates, not confirmation of account credits. [Meta SAM pricing](https://dev.meta.ai/models/sam-3-1), [Baseten pricing](https://www.baseten.co/library/muse-spark-open/).
- **Still empirical:** access from Kazakhstan, latency, effective resolution, glossy tile recall, crop merging, RU/KZ audio quality, actual account rate limits, and the team plan's credit allowance. Record observations instead of treating these as guarantees.

The referenced `.claude/skills/meta-model-api/SKILL.md` is missing from this checkout. Attempts to retrieve that path and the `hackathon-idea` tree from `diasdev-ds/orbital-` through the connected GitHub tool returned 404. That can mean the resource is absent or inaccessible to this connection; it does not prove the repository does not exist. The official sources above provide the setup reference until the teammate supplies the missing file.

## October 27 smoke-test sequence

1. Confirm the official development start time with the organizer; the team plan gives a start date without an exact time. Verify only presence of required secrets and local file permissions, never their contents in logs.
2. Confirm models available to the account. Baseten documents the authenticated `GET /v1/models` catalog; inspect model IDs without logging authorization headers. [Baseten's official hackathon starter](https://github.com/basetenlabs/Hack-the-North-2026).
3. Send one small, consented tile image to SAM with the concept `tile`. Save the response privately first. Record timestamp, model ID, source dimensions, request latency, match count, mask dimensions, and request ID. Decode one mask and verify its alignment visually. Publish a raw response under `data/samples/` only after the corresponding image and metadata are approved for public release.
4. Check zero matches and an invalid image produce useful warnings rather than invented area. Verify source orientation, box conventions, and mask placement before geometry work.
5. Compare full resolution and overlapping 3×3 crops on one wall before running the 20-wall benchmark. Compare `tile`, `wall tile`, and `ceramic tile` separately. Cache by image bytes plus model, prompt, crop transform, and relevant request settings.
6. Have the agent owner run a short Baseten text call, then one image and one synthetic tool call. Test RU/KZ audio separately. Do not substitute an unsupported `response_format` for application-side validation.
7. Stop on authentication or model-access errors; fix configuration before retrying. Use bounded backoff for temporary throttling. Reconcile actual usage with the team's $10/day planning allowance and $30–50 judging reserve; those figures are planning limits, not enforced provider settings.
8. Record results and outstanding issues for the October 27 schema review and the gate requiring at least 30 reliable masks on at least 16 of 20 walls. Do not label a fixture or cached placeholder as a successful live API test.
