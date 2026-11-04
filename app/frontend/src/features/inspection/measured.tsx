import { useI18n } from "@/lib/i18n"
import { useState } from "react"
import { Expand, ImageOff } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import type { WallResult } from "./api"

// measure/README.md: what each warning asks the user to do.
const warningText: Record<string, string> = {
  wall_out_of_frame:
    "Step back so the whole tiled wall plus a margin is in the photo.",
  undetected_area:
    "Part of the wall was not recognised (glare, cover). Retake in even light.",
  other_surface:
    "Part of the wall doesn't look like this tile (a panel, other tile, glare). It isn't counted, only allowed for.",
  uncounted_tiles:
    "Tiles seem to continue beyond the counted area. Retake it closer, in even light.",
  exclusion_overlaps_tiles:
    "A door, window or mirror was detected over visible tiles. The tiles are still counted.",
  high_residual:
    "The joints don't fit one flat grid. Use the main camera at 1×, straight on, one wall per photo.",
  too_few_tiles:
    "Too few whole tiles were recognised. Move closer, keep it sharp, check the tile size.",
  lattice_fit_failed:
    "The tiles don't form one grid (curved wall, herringbone, two walls in one photo).",
  segmentation_failed:
    "The measurement service was unavailable. Try again later.",
  unreadable_image: "The photo could not be opened. Use JPG or PNG.",
  exclusions_unavailable:
    "Doors, mirrors and bathtubs could not be checked on this photo.",
}

const statusLabel = {
  measured: "Measured",
  partial: "Retake recommended",
  unavailable: "Not measured",
} as const

const regionLabel: Record<string, string> = {
  door: "Door",
  window: "Window",
  mirror: "Mirror",
  bathtub: "Bathtub",
  toilet: "Toilet",
  sink: "Sink",
  cabinet: "Cabinet",
  undetected: "Unrecognised area",
  other_surface: "Other surface",
}

const reasonLabel: Record<string, string> = {
  opening: "opening, not billed",
  not_tiled: "not tiled",
  not_visible: "hidden, may be tiled",
}

export function MeasuredWalls({ walls }: { walls: WallResult[] }) {
  const { t, number } = useI18n()
  const [index, setIndex] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const wall = walls[Math.min(index, walls.length - 1)]
  if (!wall) return null
  const sigma2 =
    wall.sigma_random_m2 !== null && wall.sigma_system_m2 !== null
      ? 2 * (wall.sigma_random_m2 + wall.sigma_system_m2)
      : null
  const image = (
    <div className="evidence-image">
      {!wall.overlay_png || failed === wall.overlay_png ? (
        <div className="image-failure">
          <ImageOff />
          <p>{t("The measurement image could not load.")}</p>
        </div>
      ) : (
        <img
          className="measured-overlay"
          src={wall.overlay_png}
          alt={t("Tiles recognised on {wall}", { wall: wall.wall_id })}
          onError={() => setFailed(wall.overlay_png)}
        />
      )}
    </div>
  )
  return (
    <section className="panel evidence-panel" aria-labelledby="measured-title">
      <div className="panel-heading">
        <div>
          <h2 id="measured-title">{t("Wall measurements")}</h2>
          <span className="subtle">
            {t(
              "Teal tiles were recognised and counted; amber is other counted area; grey is excluded."
            )}
          </span>
        </div>
        <Badge variant="outline">
          {t("Walls: {count}", { count: walls.length })}
        </Badge>
      </div>
      <div className="evidence-body">
        <div className="viewer-column">
          <div className="viewer-frame">
            {image}
            <Button
              variant="secondary"
              size="icon-sm"
              className="expand-view"
              aria-label={t("Expand wall photo")}
              onClick={() => setExpanded(true)}
            >
              <Expand />
            </Button>
          </div>
          {walls.length > 1 && (
            <div className="wall-thumbnails" aria-label={t("Select a wall")}>
              {walls.map((item, i) => (
                <button
                  key={item.wall_id}
                  onClick={() => setIndex(i)}
                  className={cn("wall-thumb", i === index && "selected")}
                  aria-pressed={i === index}
                >
                  <div className="thumb-image">
                    {item.overlay_png && <img src={item.overlay_png} alt="" />}
                  </div>
                  <div>
                    <strong>{item.wall_id}</strong>
                    <span>
                      {item.tiled_area_m2 === null
                        ? t(statusLabel[item.status])
                        : `${number(item.tiled_area_m2, 2)} ${t("m²")}`}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
        <aside className="wall-details">
          <div className="eyebrow">
            {wall.wall_id} · {t(statusLabel[wall.status])}
          </div>
          <div className="wall-area">
            {wall.tiled_area_m2 === null ? "—" : number(wall.tiled_area_m2, 2)}{" "}
            <span>{t("m²")}</span>
          </div>
          {sigma2 !== null && (
            <div className="uncertainty">
              ± {number(sigma2, 2)} {t("m² (2σ)")}
            </div>
          )}
          <dl className="detail-list">
            <div>
              <dt>{t("Reference tile")}</dt>
              <dd>
                {number(wall.tile.width_mm)} × {number(wall.tile.height_mm)}{" "}
                {t("mm")}
              </dd>
            </div>
            {wall.full_tiles !== null && (
              <div>
                <dt>{t("Whole tiles recognised")}</dt>
                <dd>{wall.full_tiles}</dd>
              </div>
            )}
            {wall.excluded.map((e, i) => (
              <div key={i}>
                <dt>
                  {regionLabel[e.label] ? t(regionLabel[e.label]) : e.label} ·{" "}
                  {t(reasonLabel[e.reason] ?? e.reason)}
                </dt>
                <dd>
                  {number(e.area_m2, 2)} {t("m²")}
                </dd>
              </div>
            ))}
          </dl>
          {wall.warnings
            .filter((w) => warningText[w])
            .map((w) => (
              <div className="exclusion-note" key={w}>
                <div className="exclusion-swatch" />
                <p>{t(warningText[w])}</p>
              </div>
            ))}
        </aside>
      </div>
      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent className="photo-dialog">
          <DialogHeader>
            <DialogTitle>{wall.wall_id}</DialogTitle>
            <DialogDescription>
              {t(
                "Teal tiles were recognised and counted; amber is other counted area; grey is excluded."
              )}
            </DialogDescription>
          </DialogHeader>
          {image}
        </DialogContent>
      </Dialog>
    </section>
  )
}
