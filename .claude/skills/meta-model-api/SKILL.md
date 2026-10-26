---
name: meta-model-api
description: Reference for calling Meta models in ActCheck — SAM 3.1, Muse Spark 1.3/1.2 (Meta Model API), Muse Spark Open (Baseten/Fireworks), Muse Voice Transcribe. Load before writing or debugging any code that calls a Meta model, parses SAM output, sets up structured JSON output or tool calling, or estimates API cost.
---

# Meta Model API — ActCheck reference

Collected from dev.meta.ai docs on 2026-10-26. Items marked **VERIFY** were not documented and must be checked with a real call before relying on them. Never guess an API shape: if something is not here, fetch the doc page listed in "Sources".

## 1. Basics

- Base URL: `https://api.meta.ai/v1` (OpenAI-compatible). Auth: `Authorization: Bearer $MODEL_API_KEY`.
- Python: `pip install openai`; the SDK does not read `MODEL_API_KEY` itself — pass the key explicitly.
- **In this repo the key lives in `.env` as `META_API_KEY`** (not Meta's example name `MODEL_API_KEY`); model IDs and base URLs are in `.env` too (`META_SAM_MODEL`, `META_SPARK_MODEL`, `BASETEN_MODEL`, …). Load them via pydantic-settings; never hardcode, never log key values.
- Protocols: Responses (`/v1/responses`, recommended), Chat Completions, Messages (Anthropic format).
- Rate limits are per team, not per key.

```python
from openai import OpenAI
import os
meta = OpenAI(base_url=os.environ["META_API_BASE_URL"], api_key=os.environ["META_API_KEY"])
```

## 2. Models we use

| Role in ActCheck | Model ID | Price | Notes |
|---|---|---|---|
| Tile and object segmentation | `sam-3.1` | $2.50 / 1k images; video $0.20 / 1k frames (min 50 frames per request) | 3,000 RPM |
| Agent brain (Open Weights bonus) | Muse Spark Open on Baseten: `meta-models/muse-spark-open-1026` (**hackathon ID** — Meta docs say `meta-models/muse-spark-open`; use `-1026` per hackathon guide) | Baseten credits | text, image, video, audio in |
| Fallback OCR / reasoning | `muse-spark-1.3` | $1.25 in / $4.25 out per 1M tokens | text, image, video, PDF in; 1M context; **audio not fully supported in 1.3** |
| Audio fallback | `muse-spark-1.2` | same as 1.3 | docs recommend 1.2 for audio |
| Cheap dev runs | `muse-spark-1.3-contributor` | $0.10 / $0.20 | **content may be used for training** — never send private acts/photos |
| Voice | `muse-voice-transcribe-1.0` | $0.18 / hour | **Kazakh and Russian are NOT supported** (25 languages, see §6) |

Not used: `muse-image-1.0`, `muse-wonder-1.0` (Best Creative bonus skipped).

## 3. SAM 3.1

### Verified by smoke test (2026-10-26, from Almaty)
- `muse-spark-1.3` answers from Kazakhstan, 1.5–3 s for a trivial prompt.
- `sam-3.1` image request works with a base64 JPEG data URL; ~3 s for a 1200×750 image.
- Top-level `metadata={"include_confidence": "true"}` in `responses.create` works (confidence comes back).
- **Prompt wording matters a lot.** On a synthetic 40-tile wall: `"tile"` → 40/40, `"square"` → 40/40, but `"wall tile"` and `"ceramic tile"` → **0**. Default to `"tile"`; re-test prompts on real walls.
- **Each mask is cropped to its box**: mask `data=H,W` equals the box size and the mask token has `x=0;y=0` relative to the box. Paste the raster at `bounds.left/top` to get full-frame coordinates.
- Raw output sample (one record):
  `<0f>0<|box;x1=776;y1=115;x2=896;y2=242;w=1200;h=750;c=0.75|><|mask;x=0;y=0;c=0.75;data=128,121,~<base85…>|>`
- Python parser usage (async; `final_result` is a **method**):
  ```python
  import meta_sam_parser as msp
  from openai import AsyncOpenAI
  stream = await AsyncOpenAI(base_url=..., api_key=...).responses.create(model="sam-3.1", input=[...], metadata={...}, stream=True)
  async def events():
      async for e in stream:
          yield e.model_dump()
  result = await msp.parse_responses_stream(events(), msp.image_segmentation_format()).final_result()
  masks = [r for r in result.records if isinstance(r, msp.SegmentationMaskRecord)]
  # r.mask.width/height/encoding/payload, r.bounds.left/top/right/bottom, r.confidence
  raster = np.frombuffer(msp.decode_mask_to_raster(r.mask), np.uint8).reshape(r.mask.height, r.mask.width)
  ```
- A harmless `RuntimeError: aclose(): asynchronous generator is already running` may print at exit; ignore it or close the stream explicitly.

### Request (Responses API, image, concept mode)
- One user message: `input_text` (prompt) + one media part (`input_image` with `image_url`: public URL or `data:image/jpeg;base64,...`).
- **One noun phrase per request.** Lists ("tile, door"), commands, negation, OR, spatial phrases → unreliable or zero matches. For several concepts send one request each (run them in parallel).
- Plural/case/punctuation don't matter. Zero matches = empty output, not an error.
- **Image mode returns every matching instance** (no documented cap). Video tracks max 16 objects per frame.
- Max image resolution / downscaling: **VERIFY** (not documented). Test full-res vs 3×3 crops on day 1.
- `stream: true` recommended.
- Metadata (strings, not booleans): `include_confidence: "true"` adds `c` (0–1) to boxes and masks; `mask_encoding: "lossless"` (default, `~`) or `"one_bit"` (`!`).
- Metadata goes in the top-level `metadata` object of the Responses request (verified).

```python
import base64
def img_part(path):
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    return {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"}

stream = meta.responses.create(
    model="sam-3.1",
    input=[{"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "wall tile"}, img_part("wall.jpg")]}],
    metadata={"include_confidence": "true"},
    stream=True,
)
raw = "".join(e.delta for e in stream if e.type == "response.output_text.delta")
```

### Box / point prompts (instead of a noun phrase, never mixed with one)
```text
<0f>1<|box;x1=100;y1=200;x2=400;y2=500;w=1800;h=1200|>,2<|point;x=900;y=600;w=1800;h=1200|>-<|point;x=50;y=50;w=1800;h=1200|>
```
- `<0f>` for images. Integer object id, one box per object per frame, `-` before a point = negative point.
- `w`,`h` = displayed pixel size after EXIF rotation; aspect must match or HTTP 400. Max 16 prompted objects. Use `build_object_prompt` from `meta-sam-parser`.
- Useful for us: re-segment a suspected merged region with positive points on individual tiles.

### Output format
- Text lines; each line = frame marker `<Nf>` then comma-separated records: `object_id box_token mask_token`.
- Boxes: `x1,y1,x2,y2` in **source pixels** (not normalised), plus `w`,`h` = source frame size.
- Masks: `data=<H>,<W>,<enc>payload`, `~` lossless / `!` one_bit, payload **base85**.
- Exact token punctuation: see the verified raw sample above. Use the official parser rather than hand-parsing.
- Decode with the official parser: `pip install meta-sam-parser` (Python ≥3.10) → `decode_mask_to_raster`, `decode_mask_to_rle`, `decode_mask_to_svg_path`, `build_object_prompt`. Raster = row-major 0/1, length H×W.
- Results can vary slightly between runs → **cache responses on disk keyed by sha256(image bytes + prompt + metadata)**.

### Errors
- 400: bad prompt/metadata (mixed noun phrase + boxes, duplicate ids, wrong w/h, >16 objects). Don't retry unchanged.
- 404 `model_not_found`.

### Local fallback
Weights `facebook/sam3`, `facebook/sam3.1` on Hugging Face (gated; request access early).

## 4. Muse Spark 1.3 (Meta API)

### Structured output
- Chat Completions: `response_format={"type":"json_schema","json_schema":{"name":..., "schema":..., "strict": True}}` → JSON string in `choices[0].message.content`. Or `client.beta.chat.completions.parse(..., response_format=PydanticModel)` → `.parsed`.
- Responses API: `text={"format": {...}}` — **not** `response_format`; the two are not interchangeable.
- Strict mode: `additionalProperties: false` everywhere, all properties in `required`, no top-level `anyOf/oneOf/allOf/enum/not`. No recursive schemas (HTTP 400). Max 10 nesting levels.

### Tool calling
- Responses API: tools as `{"type":"function","name":...,"description":...,"parameters":{...}}` (flat). Chat Completions: nested under `"function"`.
- `tool_choice` supports **only `"auto"`** — `"required"`/`"none"`/named → HTTP 400. The loop must handle both a tool call and a plain text reply.
- Parallel calls possible; return one result per call. `parallel_tool_calls: false` forces one per turn.
- Return results (Responses): `{"type":"function_call_output","call_id":...,"output": json.dumps(result)}` + `previous_response_id`.
- `strict: true` validates the schema only; model arguments are not guaranteed valid → validate with pydantic and retry.
- Bound the agent loop yourself (max turns); `max_tool_calls` only limits built-in tools.

### Media input
Image/PDF content part types: see Image understanding and File handling docs (**VERIFY** exact PDF part on day 1).

## 5. Muse Spark Open (Open Weights bonus)

- 816B MoE, 42B active; text/image/video/audio in; 1M context; 100+ languages. Licence: Muse Model License + Acceptable Use Policy.
- **Baseten** (our primary): `base_url="https://inference.baseten.co/v1"`, key `BASETEN_API_KEY`, model `meta-models/muse-spark-open-1026`. Media as OpenAI content parts `image_url`, `video_url`, `audio_url`; send >74 MB by URL.
- **Fireworks** (backup): `base_url="https://api.fireworks.ai/inference/v1"`, model `accounts/fireworks/models/muse-spark-open`, `FIREWORKS_API_KEY`. Tool calling via OpenAI `tools` (→ `message.tool_calls`); JSON mode `response_format={"type":"json_object"}`; `reasoning_effort` low/medium/high/xhigh (default xhigh — set lower for latency).
- Baseten docs: tool calling and multimodal input are supported, but **Spark Open is excluded from structured outputs and JSON mode**. So: tools for actions, and for data extraction ask for JSON in the prompt → parse → pydantic validate → bounded repair retry (feed the validation error back) → clear failure state. Never pass `response_format` to Baseten.
- Model ID: hackathon guide says `meta-models/muse-spark-open-1026`; Baseten's public page says `meta-models/muse-spark-open`. Resolve with `GET https://inference.baseten.co/v1/models` once the key exists and put the result in `BASETEN_MODEL` in `.env`.
- For the bonus, the judged pipeline must actually run on Spark Open — keep the Meta-API Spark path as an explicit fallback flag, not the default.

```python
spark_open = OpenAI(base_url="https://inference.baseten.co/v1", api_key=os.environ["BASETEN_API_KEY"])
r = spark_open.chat.completions.create(
    model="meta-models/muse-spark-open-1026",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "Extract all lines of this act as JSON."},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
    ]}],
)
```

## 6. Voice notes (Russian / Kazakh)

- `muse-voice-transcribe-1.0` supports 25 languages; **Kazakh and Russian are not among them**. Do not use it for our users' notes.
- Plan: send the audio straight to **Muse Spark Open** (`audio_url` content part) and ask for transcript + structured facts ("bathtub covers lower part of wall 2"). Fallback: `muse-spark-1.2` (audio-capable) on the Meta API.
- If ever used for English: `POST /v1/asr/transcribe`, multipart (`request` JSON + `audio` WAV mono 16-bit PCM 16/24 kHz), ≤10 min, ≤32 MB; `languageBias` is a hint list.

## 7. Cost guardrails

- Budget ~$10/person/day; keep $30–50 reserve for judging (Nov 5–8).
- SAM: 20 walls × ~4 prompts ≈ 80 images ≈ $0.20. Cheap — the risk is Spark tokens and Spark Open, not SAM.
- Always cache; never re-run SAM on the same image+prompt.
- Do not use `-contributor` models with private acts or photos.

## Sources
- https://dev.meta.ai/docs/quickstart · /docs/models · /docs/pricing-rate-limits
- https://dev.meta.ai/docs/media-segmentation · /docs/sam/segmenting · /docs/sam/reading-segmentation · /docs/sam/client-libraries
- https://dev.meta.ai/docs/structured-output · /docs/tool-calling · /docs/image-understanding · /docs/file-handling
- https://dev.meta.ai/docs/muse-spark-open · /docs/muse-spark-open/deploy
- https://dev.meta.ai/docs/speech-to-text
- Cookbook: https://github.com/meta-models/meta-model-cookbook
