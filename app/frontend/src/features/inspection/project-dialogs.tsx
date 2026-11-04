import { useI18n } from "@/lib/i18n"
import { useRef, useState, type FormEvent } from "react"
import { Camera, FileText, Info, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { cn } from "@/lib/utils"
import type { LocalFile, Project } from "./data"
import { caseFile, testCases } from "./test-cases"

export function NewProjectDialog({
  open,
  onOpenChange,
  onCreate,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreate: (project: Project) => void
}) {
  const { t, number } = useI18n()

  const [error, setError] = useState("")
  // Both sides under 10 cm usually means centimetres typed as millimetres.
  const [small, setSmall] = useState<Project | null>(null)
  function create(project: Project) {
    onCreate(project)
    setError("")
    setSmall(null)
    onOpenChange(false)
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const name = String(data.get("name") ?? "").trim()
    const tileWidth = Number(data.get("width")),
      tileHeight = Number(data.get("height"))
    if (
      !name ||
      !Number.isFinite(tileWidth) ||
      !Number.isFinite(tileHeight) ||
      tileWidth < 10 ||
      tileHeight < 10 ||
      tileWidth > 2000 ||
      tileHeight > 2000
    ) {
      setError(
        "Enter a project name and tile dimensions between 10 and 2,000 mm."
      )
      return
    }
    const project: Project = {
      id: `AC-${crypto.randomUUID().slice(0, 6).toUpperCase()}`,
      name,
      location: String(data.get("location") ?? "").trim(),
      tileWidth,
      tileHeight,
      example: false,
      files: [],
      notes: "",
    }
    if (tileWidth < 100 && tileHeight < 100) {
      setError("")
      setSmall(project)
      return
    }
    create(project)
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("New inspection")}</DialogTitle>
          <DialogDescription>
            {t(
              "Start with the room and tile size. Add your statement and photos next."
            )}
          </DialogDescription>
        </DialogHeader>
        <form noValidate onSubmit={submit}>
          <FieldGroup>
            <Field data-invalid={!!error}>
              <FieldLabel htmlFor="project-name">
                {t("Project name")}
              </FieldLabel>
              <Input
                id="project-name"
                name="name"
                placeholder={t("e.g. Guest bathroom")}
                autoComplete="off"
                maxLength={80}
                required
                aria-invalid={!!error}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="project-location">
                {t("Location")}
                <span className="subtle">{t("(optional)")}</span>
              </FieldLabel>
              <Input
                id="project-location"
                name="location"
                placeholder={t("City or project reference")}
                maxLength={100}
              />
            </Field>
            <div className="two-fields">
              <Field>
                <FieldLabel htmlFor="tile-width">
                  {t("Tile width, mm")}
                </FieldLabel>
                <Input
                  id="tile-width"
                  name="width"
                  type="number"
                  min="10"
                  max="2000"
                  step="0.1"
                  inputMode="decimal"
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="tile-height">
                  {t("Tile height, mm")}
                </FieldLabel>
                <Input
                  id="tile-height"
                  name="height"
                  type="number"
                  min="10"
                  max="2000"
                  step="0.1"
                  inputMode="decimal"
                  required
                />
              </Field>
            </div>
            <FieldDescription>
              {t(
                "Copy them from the box label: every area is computed from this size. Projects and files stay in this browser tab and are cleared on reload."
              )}
            </FieldDescription>
            {error && (
              <p role="alert" className="form-error">
                {t(error)}
              </p>
            )}
            {small && (
              <Alert role="alert">
                <Info />
                <AlertTitle>
                  {t(
                    "{width} × {height} mm is a mosaic. Did you mean centimetres?",
                    {
                      width: number(small.tileWidth),
                      height: number(small.tileHeight),
                    }
                  )}
                </AlertTitle>
                <AlertDescription>
                  <div className="analysis-actions">
                    <Button
                      type="button"
                      onClick={() =>
                        create({
                          ...small,
                          tileWidth: small.tileWidth * 10,
                          tileHeight: small.tileHeight * 10,
                        })
                      }
                    >
                      {t("Use {width} × {height} mm", {
                        width: number(small.tileWidth * 10),
                        height: number(small.tileHeight * 10),
                      })}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => create(small)}
                    >
                      {t("Keep {width} × {height} mm", {
                        width: number(small.tileWidth),
                        height: number(small.tileHeight),
                      })}
                    </Button>
                  </div>
                </AlertDescription>
              </Alert>
            )}
          </FieldGroup>
          <DialogFooter className="form-footer">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              {t("Cancel")}
            </Button>
            <Button type="submit">{t("Create inspection")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

type Role = "act" | "wall"

const uploadKinds: {
  role: Role
  icon: typeof FileText
  title: string
  hint: string
  accept: string
}[] = [
  {
    role: "act",
    icon: FileText,
    title: "Statement pages",
    hint: "Photo or PDF of the work statement",
    accept: "image/jpeg,image/png,image/webp,application/pdf",
  },
  {
    role: "wall",
    icon: Camera,
    title: "Wall photos",
    hint: "One photo per tiled wall, all edges in frame",
    accept: "image/jpeg,image/png,image/webp",
  },
]

export function UploadDialog({
  open,
  onOpenChange,
  files,
  onAdd,
  onRemove,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  files: LocalFile[]
  onAdd: (files: File[], role: Role) => Promise<void>
  onRemove: (id: string) => void
}) {
  const { t, number } = useI18n()

  const inputs = useRef<Partial<Record<Role, HTMLInputElement | null>>>({})
  const adding = useRef(false)
  const [dragging, setDragging] = useState<Role | null>(null)
  const [busy, setBusy] = useState(false)
  async function add(items: File[], role: Role) {
    if (adding.current) return
    adding.current = true
    setBusy(true)
    try {
      await onAdd(items, role)
    } finally {
      adding.current = false
      setBusy(false)
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("Add evidence")}</DialogTitle>
          <DialogDescription>
            {t(
              "Add the work statement and one photo per wall, each with its own button."
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="upload-zones">
          {uploadKinds.map(({ role, icon: Icon, title, hint, accept }) => (
            <div key={role}>
              <input
                ref={(node) => {
                  inputs.current[role] = node
                }}
                type="file"
                accept={accept}
                multiple
                disabled={busy}
                className="sr-only"
                aria-label={t(title)}
                onChange={(event) => {
                  void add(Array.from(event.target.files ?? []), role)
                  event.target.value = ""
                }}
              />
              <button
                className={cn("upload-zone", dragging === role && "dragging")}
                disabled={busy}
                onClick={() => inputs.current[role]?.click()}
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragging(role)
                }}
                onDragLeave={() => setDragging(null)}
                onDrop={(event) => {
                  event.preventDefault()
                  setDragging(null)
                  if (!busy)
                    void add(Array.from(event.dataTransfer.files), role)
                }}
              >
                <span className="upload-icon">
                  <Icon />
                </span>
                <strong>
                  {t(title)} ·{" "}
                  {files.filter((item) => item.role === role).length}
                </strong>
                <span>{busy ? t("Checking files…") : t(hint)}</span>
              </button>
            </div>
          ))}
        </div>
        <div className="upload-list" aria-live="polite">
          {files.map((item) => (
            <div key={item.id} className="upload-item">
              {item.role === "wall" ? (
                <Camera size={18} />
              ) : (
                <FileText size={18} />
              )}
              <div>
                <strong>{item.file.name}</strong>
                <span>
                  {t(item.role === "wall" ? "Wall photo" : "Statement page")} ·{" "}
                  {number(item.file.size / 1024 / 1024, 2)} {t("MB")}
                </span>
              </div>
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={() => onRemove(item.id)}
                aria-label={t("Remove {name}", { name: item.file.name })}
              >
                <X />
              </Button>
            </div>
          ))}
        </div>
        <Alert>
          <Info />
          <AlertTitle>
            {t("Nothing is sent until you run the analysis")}
          </AlertTitle>
          <AlertDescription>
            {t(
              "Then the files go to our server and the Meta Model API. JPG, PNG, WebP or PDF, 20 MB per file, up to 12 files."
            )}
          </AlertDescription>
        </Alert>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)} disabled={busy}>
            {t("Done")}{" "}
            {files.length
              ? ` · ${t("Files: {count}", { count: files.length })}`
              : ""}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function CaptureGuide({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useI18n()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("A good photo makes the difference.")}</DialogTitle>
          <DialogDescription>
            {t("A short checklist for a useful room inspection.")}
          </DialogDescription>
        </DialogHeader>
        <ol className="capture-steps">
          <li>
            <span>01</span>
            <div>
              <h3>{t("Keep the entire wall in frame")}</h3>
              <p>
                {t(
                  "Use your main camera, face the wall straight on, and include all edges of the tiled surface."
                )}
              </p>
            </div>
          </li>
          <li>
            <span>02</span>
            <div>
              <h3>{t("Give the room a reference")}</h3>
              <p>
                {t(
                  "Photograph the tile box label or measure one tile. Include both width and height in millimetres."
                )}
              </p>
            </div>
          </li>
          <li>
            <span>03</span>
            <div>
              <h3>{t("Use even, natural light")}</h3>
              <p>
                {t(
                  "Avoid reflections, blur, and the ultrawide lens. Take one separate photo for each wall."
                )}
              </p>
            </div>
          </li>
          <li>
            <span>04</span>
            <div>
              <h3>{t("Keep the supporting records")}</h3>
              <p>
                {t(
                  "A finished wall cannot prove hidden work. Keep photos and records of waterproofing and preparation."
                )}
              </p>
            </div>
          </li>
        </ol>
        <section className="test-downloads" aria-labelledby="test-files-title">
          <h3 id="test-files-title">{t("Test cases")}</h3>
          <p>
            {t(
              "Each case has a contractor act, a wall photo and a report with the true measurements and the expected result. Enter the tile size shown."
            )}
          </p>
          <ul className="test-cases">
            {testCases.map((item) => (
              <li key={item.id}>
                <div>
                  <strong>{t(item.title)}</strong>
                  <span>
                    {t("Tile {size} mm", {
                      size: `${item.tile[0]} × ${item.tile[1]}`,
                    })}
                  </span>
                </div>
                <div className="test-case-links">
                  <a
                    href={caseFile(item.id, "act.jpg")}
                    download={`${item.id}_act.jpg`}
                    aria-label={`${t("Act")}: ${t(item.title)}`}
                  >
                    {t("Act")}
                  </a>
                  <a
                    href={caseFile(item.id, "wall.png")}
                    download={`${item.id}_wall.png`}
                    aria-label={`${t("Wall photo")}: ${t(item.title)}`}
                  >
                    {t("Wall photo")}
                  </a>
                  <a
                    href={caseFile(item.id, "report.html")}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`${t("Report")}: ${t(item.title)}`}
                  >
                    {t("Report")}
                  </a>
                  <a
                    href={caseFile(item.id, "measurement.json")}
                    download={`${item.id}_measurement.json`}
                    aria-label={`${t("Data")}: ${t(item.title)}`}
                  >
                    {t("Data")}
                  </a>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </DialogContent>
    </Dialog>
  )
}
