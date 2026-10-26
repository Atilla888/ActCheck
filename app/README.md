# ActCheck application

The [frontend](frontend/README.md) is implemented at the user's request. Start it with `cd app/frontend && npm ci && npm run dev`. The FastAPI service and model integration remain unimplemented and should be coordinated with teammate A.

The frontend offers an illustrative inspection plus local drafts, evidence upload and preview, measurement review, contractor questions, notes, and HTML/print-to-PDF reports. It never computes new measurements or sends uploads to an external service.

All model credentials belong on the server. The browser must never receive Meta, Baseten, or Hugging Face secrets.
