import { useI18n } from "@/lib/i18n"
import { useRef } from "react"
import { createPortal } from "react-dom"
import { Download, Printer } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  statement,
  exampleProject,
  conservativeDifference,
  statusLabels,
  type Project,
} from "./data"

function ReportContent({ project }: { project: Project }) {
  const { t, number, money } = useI18n()

  return (
    <article className="report-document">
      <div className="report-brand">
        ActCheck <span>{t("INSPECTION REPORT")}</span>
      </div>
      <div className="report-disclaimer">
        {project.example
          ? t("ILLUSTRATIVE EXAMPLE — NOT A VERIFIED MEASUREMENT")
          : t("DRAFT — MEASUREMENTS NOT YET AVAILABLE")}
      </div>
      <h1>{project.example ? t(project.name) : project.name}</h1>
      <p>
        {project.id} ·{" "}
        {project.example
          ? t(project.location)
          : project.location || t("Location not specified")}
      </p>
      <p>
        {t("Tile reference:")} {number(project.tileWidth)} ×{" "}
        {number(project.tileHeight)} {t("mm")}
      </p>
      {project.example ? (
        <>
          <h2>{t("Measurement summary")}</h2>
          <p>
            {t("Statement: 48.5 m². Example measured area: 36.9 ± 1.1 m².")}
          </p>
          <p>
            {t(
              "At the upper measurement bound (38.0 m²), 10.5 m² of wall tiling remains to clarify:"
            )}{" "}
            <strong>{t("99,750 KZT")}</strong>{" "}
            {t(
              "at 9,500 KZT/m². This is not a confirmed saving or a payment recommendation."
            )}
          </p>
          <table>
            <thead>
              <tr>
                <th>{t("Work item")}</th>
                <th>{t("Statement")}</th>
                <th>{t("Measured")}</th>
                <th>{t("Review")}</th>
              </tr>
            </thead>
            <tbody>
              {statement.map((row) => (
                <tr key={row.id}>
                  <td>{t(row.name)}</td>
                  <td>
                    {number(row.claimed)} {t("m²")}
                  </td>
                  <td>
                    {row.measured === null
                      ? t("Not verified")
                      : `${number(row.measured)} ± ${number(row.uncertainty ?? 0)} ${t("m²")}`}
                  </td>
                  <td>{t(statusLabels[row.status])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2>{t("Questions before payment")}</h2>
          <ol>
            {statement
              .filter((row) => row.status !== "matched")
              .map((row) => (
                <li key={row.id}>
                  {t(row.question)}
                  {row.status === "review" && (
                    <p>
                      {t("Illustrative amount to clarify: at least")}{" "}
                      {money(conservativeDifference(row) ?? 0)} {t("KZT.")}
                    </p>
                  )}
                </li>
              ))}
          </ol>
          <h2>{t("Limitations")}</h2>
          <p>
            {t(
              "All quantities and the room image are synthetic demonstration fixtures. No live model has inspected this room. Hidden areas, waterproofing, and surface preparation are not verified. The uncertainty shown is illustrative, not an empirically validated confidence interval."
            )}
          </p>
        </>
      ) : (
        <>
          <h2>{t("Inspection status")}</h2>
          <p>
            {t(
              "Evidence is staged locally. Live analysis is not connected. No measurements, discrepancies, or amounts to clarify have been established."
            )}
          </p>
          <h2>{t("Evidence manifest")}</h2>
          {project.files.length ? (
            <ul>
              {project.files.map((item) => (
                <li key={item.id}>
                  {item.file.name} ({t(item.kind)})
                </li>
              ))}
            </ul>
          ) : (
            <p>{t("No evidence files added.")}</p>
          )}
        </>
      )}
      {project.notes && (
        <>
          <h2>{t("Reviewer notes")}</h2>
          <p className="preserve-lines">
            {project.example && project.notes === exampleProject.notes
              ? t(project.notes)
              : project.notes}
          </p>
        </>
      )}
      <footer>
        {t(
          "Prepared in ActCheck · Review the supporting evidence with your contractor."
        )}
      </footer>
    </article>
  )
}

export function ReportDialog({
  open,
  onOpenChange,
  project,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  project: Project
}) {
  const { t, locale } = useI18n()

  const ref = useRef<HTMLDivElement>(null)
  function download() {
    if (!ref.current) return
    const styles =
      "body{font:15px/1.6 system-ui,sans-serif;color:#232731;max-width:850px;margin:40px auto;padding:24px}h1{font-size:30px}h2{font-size:18px;margin-top:30px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:12px 8px;border-bottom:1px solid #ddd;text-align:left}footer{margin-top:40px;color:#667085;font-size:12px}.report-disclaimer{border:1px solid #ddd;padding:12px;margin:24px 0;font-size:12px}.report-brand{font-weight:700}.report-brand span{float:right;font-size:12px;letter-spacing:2px}.preserve-lines{white-space:pre-wrap}li{margin:12px 0}"
    const blob = new Blob(
      [
        `<!doctype html><html lang="${locale}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ActCheck — ${t("Inspection report")}</title><style>${styles}</style><body>${ref.current.innerHTML}</body></html>`,
      ],
      { type: "text/html;charset=utf-8" }
    )
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `${project.id}-inspection-report.html`
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="report-dialog">
          <DialogHeader>
            <DialogTitle>{t("Inspection report")}</DialogTitle>
            <DialogDescription>
              {t(
                "Review the report, then print or save it as a PDF from your browser."
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="report-preview" ref={ref}>
            <ReportContent project={project} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={download}>
              <Download data-icon="inline-start" />
              {t("Download HTML")}
            </Button>
            <Button onClick={() => window.print()}>
              <Printer data-icon="inline-start" />
              {t("Print / save PDF")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {open &&
        createPortal(
          <div className="print-report">
            <ReportContent project={project} />
          </div>,
          document.body
        )}
    </>
  )
}
