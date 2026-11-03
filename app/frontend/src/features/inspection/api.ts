import type { Locale } from "@/lib/i18n"
import type { LocalFile, Project, ReviewStatus, StatementLine } from "./data"

// Mirrors schemas/ and app/server/files.py:to_view. Server paths arrive as URLs.
export type Verdict =
  | "consistent"
  | "over_billed"
  | "under_billed"
  | "not_verifiable"
  | "incomplete"

export type Comparison = {
  line_no: number
  description_raw: string
  unit: string
  billed_qty: number | null
  measured_qty: number | null
  measured_low: number | null
  measured_high: number | null
  verdict: Verdict
  overbilling_min: number | null
  evidence: string[]
  explanation: string
  question: string
}

export type WallResult = {
  wall_id: string
  status: "measured" | "partial" | "unavailable"
  tile: { width_mm: number; height_mm: number }
  full_tiles: number | null
  partial_tiles_equiv: number | null
  tiled_area_m2: number | null
  sigma_random_m2: number | null
  sigma_system_m2: number | null
  excluded: { label: string; area_m2: number; reason: string }[]
  overlay_png: string | null
  warnings: string[]
}

export type InspectionView = {
  act: {
    currency: string
    lines: {
      line_no: number
      work_type: string
      unit_price: number | null
      amount_stated: number | null
    }[]
  }
  protocol: {
    comparisons: Comparison[]
    verifiable_share: number
    overbilling_min_total: number
    questions: string[]
    summary: string
  }
  room: { walls: WallResult[]; unverified_walls: string[] } | null
  act_pages: (string | null)[]
  sample?: boolean
}

export type JobStatus =
  | "queued"
  | "parsing"
  | "measuring"
  | "counting"
  | "protocol"
  | "done"
  | "failed"

export type Job = {
  id: string
  status: JobStatus
  result: InspectionView | null
  error: string | null
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export async function fetchSample(locale: Locale) {
  return json<InspectionView>(await fetch(`/api/sample?lang=${locale}`))
}

export async function startInspection(project: Project, locale: Locale) {
  const form = new FormData()
  const role = (f: LocalFile) =>
    f.role ?? (f.kind === "document" ? "act" : "wall")
  for (const f of project.files)
    form.append(role(f) === "act" ? "act" : "walls", f.file)
  form.append("tile_width_mm", String(project.tileWidth))
  form.append("tile_height_mm", String(project.tileHeight))
  form.append("tile_source", "box_label")
  form.append("lang", locale)
  return json<Job>(
    await fetch("/api/inspections", { method: "POST", body: form })
  )
}

// null: the server no longer knows the job (it restarted; jobs live in memory).
export async function getInspection(id: string): Promise<Job | null> {
  const response = await fetch(`/api/inspections/${id}`)
  if (response.status === 404) return null
  return json<Job>(response)
}

const statusOf: Record<Verdict, ReviewStatus> = {
  consistent: "matched",
  under_billed: "matched",
  over_billed: "review",
  incomplete: "incomplete",
  not_verifiable: "unverified",
}

export function statementRows(view: InspectionView): StatementLine[] {
  const lines = new Map(view.act.lines.map((l) => [l.line_no, l]))
  return view.protocol.comparisons.map((c) => {
    const line = lines.get(c.line_no)
    const measured = c.measured_qty
    return {
      id: String(c.line_no).padStart(2, "0"),
      name: c.description_raw,
      detail: c.unit,
      unit: c.unit,
      claimed: c.billed_qty ?? 0,
      measured,
      // ± is the 2σ spread below the estimate; the upper bound also holds hidden areas
      uncertainty:
        measured !== null && c.measured_low !== null
          ? Math.max(0, measured - c.measured_low)
          : null,
      upper: c.measured_high,
      rate: line?.unit_price ?? 0,
      amount: line?.amount_stated ?? null,
      status: statusOf[c.verdict],
      toClarify: c.overbilling_min,
      explanation: c.explanation,
      question: c.question,
      live: true,
    }
  })
}
