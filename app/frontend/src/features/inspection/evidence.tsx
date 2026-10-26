import { useI18n } from "@/lib/i18n"
import { useId, useState } from "react"
import { Expand, ScanLine, Layers2, ArrowUpRight, ImageOff } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { walls } from "./data"

function TileOverlay() {
  const clipId = useId()
  const xs = [154, 284, 438, 597, 756, 920, 1000]
  const ys = [25, 143, 262, 382, 500, 619, 737, 855, 968]
  return (
    <svg
      className="tile-overlay"
      viewBox="0 0 1000 1000"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <clipPath id={clipId}>
          <path d="M154 25 H1000 V734 H533 V968 H154 Z" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clipId})`}>
        {ys.slice(0, -1).flatMap((y, row) =>
          xs.slice(0, -1).map((x, col) => (
            <g key={`${row}-${col}`}>
              <rect
                x={x + 2}
                y={y + 3}
                width={xs[col + 1] - x - 4}
                height={ys[row + 1] - y - 6}
                rx="2"
              />
              <text
                x={(x + xs[col + 1]) / 2}
                y={(y + ys[row + 1]) / 2}
                dominantBaseline="middle"
                textAnchor="middle"
              >
                {String(row * 6 + col + 1).padStart(2, "0")}
              </text>
            </g>
          ))
        )}
      </g>
    </svg>
  )
}

export function EvidenceViewer() {
  const { t, number } = useI18n()

  const [wallIndex, setWallIndex] = useState(0)
  const [overlay, setOverlay] = useState(true)
  const [expanded, setExpanded] = useState(false)
  const [failed, setFailed] = useState(false)
  const wall = walls[wallIndex]
  const view = (
    <div className="evidence-image">
      {failed ? (
        <div className="image-failure">
          <ImageOff />
          <p>{t("Example image could not load.")}</p>
          <p>{t("The sample measurement details remain available.")}</p>
        </div>
      ) : (
        <div className="image-scene">
          <img
            src="/images/example-bathroom.png"
            alt={t(
              "Synthetic example of a ceramic-tiled bathroom wall with a bathtub; not a measured site"
            )}
            onError={() => setFailed(true)}
          />
          {overlay && <TileOverlay />}
        </div>
      )}
      <div className="image-topline">
        <span className="image-tag">
          <span />
          {t(wall.name)}
        </span>
        <span className="image-tag image-tag-muted">
          {t("Illustrative image")}
        </span>
      </div>
      {!failed && (
        <div className="image-bottomline">
          <span>
            <ScanLine size={14} />
            {overlay
              ? t("Illustrative segmentation")
              : t("Original example image")}
          </span>
          <span>
            {t("WALL")} {wall.id}
          </span>
        </div>
      )}
    </div>
  )
  return (
    <section className="panel evidence-panel" aria-labelledby="evidence-title">
      <div className="panel-heading">
        <div>
          <h2 id="evidence-title">{t("Visual evidence")}</h2>
          <span className="subtle">{t("Four walls. One clear picture.")}</span>
        </div>
        <Badge variant="outline">{t("4 sample walls")}</Badge>
      </div>
      <div className="evidence-body">
        <div className="viewer-column">
          <div className="viewer-frame">
            {view}
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
          <div className="viewer-controls">
            <label htmlFor="overlay-toggle">
              <Layers2 size={15} /> {t("Show tile overlay")}
            </label>
            <Switch
              id="overlay-toggle"
              checked={overlay}
              onCheckedChange={setOverlay}
            />
            <span className="viewer-caption">{t("Synthetic example")}</span>
          </div>
          <div
            className="wall-thumbnails"
            aria-label={t("Select a sample wall")}
          >
            {walls.map((item, i) => (
              <button
                key={item.id}
                onClick={() => setWallIndex(i)}
                className={cn("wall-thumb", i === wallIndex && "selected")}
                aria-pressed={i === wallIndex}
                aria-label={t("View {name}", { name: t(item.name) })}
              >
                <div className={cn("thumb-image", `thumb-${i}`)}>
                  <img src="/images/example-bathroom.png" alt="" />
                  <span>{item.id}</span>
                </div>
                <div>
                  <strong>{t(item.name)}</strong>
                  <span>
                    {number(item.area)} {t("m²")}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
        <aside className="wall-details">
          <div className="eyebrow">
            {t("WALL")} {wall.id} {t("/ MEASUREMENT")}
          </div>
          <h3>{t(wall.name)}</h3>
          <div className="wall-area">
            {number(wall.area)} <span>{t("m²")}</span>
          </div>
          <div className="uncertainty">
            ± {number(wall.sigma)} {t("m² estimated uncertainty")}
          </div>
          <dl className="detail-list">
            <div>
              <dt>{t("Reference tile")}</dt>
              <dd>{t("300 × 600 mm")}</dd>
            </div>
            <div>
              <dt>{t("Tile equivalents")}</dt>
              <dd>{wall.tiles}</dd>
            </div>
            <div>
              <dt>{t("Excluded area")}</dt>
              <dd>
                {number(wall.excluded)} {t("m²")}
              </dd>
            </div>
            <div>
              <dt>{t("Source")}</dt>
              <dd>{t("Example fixture")}</dd>
            </div>
          </dl>
          <div className="exclusion-note">
            <div className="exclusion-swatch" />
            <div>
              <strong>{t("Occluded areas excluded")}</strong>
              <p>
                {t("Behind the bathtub cannot be verified from this view.")}
              </p>
            </div>
          </div>
          <div className="wall-bottom-note">
            <ArrowUpRight size={15} />
            <span>
              {t(
                "Dimensions illustrate the review workflow. No live model has measured this image."
              )}
            </span>
          </div>
        </aside>
      </div>
      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent className="photo-dialog">
          <DialogHeader>
            <DialogTitle>
              {t(wall.name)} {t("· visual evidence")}
            </DialogTitle>
            <DialogDescription>
              {t(
                "Synthetic example image. The overlay illustrates segmentation; it is not model output."
              )}
            </DialogDescription>
          </DialogHeader>
          {view}
          <div className="photo-dialog-caption">
            {t("Sample area:")} {number(wall.area)} ± {number(wall.sigma)}{" "}
            {t("m²")}
          </div>
        </DialogContent>
      </Dialog>
    </section>
  )
}
