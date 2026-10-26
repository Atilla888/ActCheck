export type ReviewStatus = "review" | "matched" | "unverified"
export type StatementLine = {
  id: string
  name: string
  detail: string
  claimed: number
  measured: number | null
  uncertainty: number | null
  rate: number
  status: ReviewStatus
  explanation: string
  question: string
}

// Deliberate demo fixtures. These are not model predictions or validation results.
export const statement: StatementLine[] = [
  {
    id: "01",
    name: "Wall tiling",
    detail: "Ceramic tile · 300 × 600 mm",
    claimed: 48.5,
    measured: 36.9,
    uncertainty: 1.1,
    rate: 9500,
    status: "review",
    explanation:
      "The example measurement is 11.6 m² below the statement. Using the upper measurement bound of 38.0 m² leaves 10.5 m² to clarify. Areas hidden behind the bathtub are not verified.",
    question:
      "Could you share the wall-by-wall calculation for the 48.5 m² of tiling, including openings and hidden areas?",
  },
  {
    id: "02",
    name: "Floor tiling",
    detail: "Porcelain tile · 600 × 600 mm",
    claimed: 6.4,
    measured: 6.3,
    uncertainty: 0.2,
    rate: 9500,
    status: "matched",
    explanation:
      "The claimed 6.4 m² falls within the illustrative measurement range of 6.1–6.5 m². This is a sample comparison, not a verified site measurement.",
    question:
      "Please confirm whether the floor quantity includes cutting allowance.",
  },
  {
    id: "03",
    name: "Tile grouting",
    detail: "Wall surfaces · 2 mm joints",
    claimed: 48.5,
    measured: 36.9,
    uncertainty: 1.1,
    rate: 1500,
    status: "review",
    explanation:
      "The same visible wall area is used for grouting in this example. Confirm the billing convention before treating this difference as an adjustment.",
    question:
      "Is grouting billed against the net tiled area or another agreed quantity?",
  },
  {
    id: "04",
    name: "Waterproofing",
    detail: "Concealed work · two coats",
    claimed: 12.8,
    measured: null,
    uncertainty: null,
    rate: 2800,
    status: "unverified",
    explanation:
      "Waterproofing is concealed beneath the finish. A photograph of completed tiling cannot establish its coverage or quality.",
    question:
      "Could you provide the waterproofing work record and photographs taken before the tiles were installed?",
  },
  {
    id: "05",
    name: "Surface preparation",
    detail: "Primer and substrate preparation",
    claimed: 48.5,
    measured: null,
    uncertainty: null,
    rate: 900,
    status: "unverified",
    explanation:
      "Primer and substrate preparation are hidden by the finished surface. They require supporting work records.",
    question:
      "Could you provide the preparation record, product used, and the area covered?",
  },
]

export const walls = [
  {
    id: "01",
    name: "North wall",
    area: 10.8,
    sigma: 0.5,
    tiles: 60,
    excluded: 1.2,
  },
  {
    id: "02",
    name: "East wall",
    area: 9.2,
    sigma: 0.5,
    tiles: 51,
    excluded: 0.8,
  },
  {
    id: "03",
    name: "South wall",
    area: 8.4,
    sigma: 0.5,
    tiles: 47,
    excluded: 1.6,
  },
  {
    id: "04",
    name: "West wall",
    area: 8.5,
    sigma: 0.6,
    tiles: 47,
    excluded: 0.4,
  },
]

export const statusLabels: Record<ReviewStatus, string> = {
  review: "Needs review",
  matched: "Within range",
  unverified: "Not verifiable",
}

export function conservativeDifference(line: StatementLine) {
  if (line.measured === null || line.uncertainty === null) return null
  return Math.max(
    0,
    Math.round((line.claimed - line.measured - line.uncertainty) * line.rate)
  )
}

export type LocalFile = {
  id: string
  file: File
  url: string
  kind: "photo" | "document"
}
export type Project = {
  id: string
  name: string
  location: string
  tileWidth: number
  tileHeight: number
  example: boolean
  files: LocalFile[]
  notes: string
}

export const exampleProject: Project = {
  id: "AC-024",
  name: "Bathroom renovation",
  location: "Almaty · Residential",
  tileWidth: 300,
  tileHeight: 600,
  example: true,
  files: [],
  notes:
    "Confirm the area behind the bathtub with the contractor. Request photos of waterproofing before the finish was installed.",
}
