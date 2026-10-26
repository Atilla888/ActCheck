import { useI18n } from "@/lib/i18n"
import { useRef, useState, type FormEvent } from "react"
import { Camera, FileText, Info, Upload, X } from "lucide-react"
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

export function NewProjectDialog({
  open,
  onOpenChange,
  onCreate,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreate: (project: Project) => void
}) {
  const { t } = useI18n()

  const [error, setError] = useState("")
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
    onCreate({
      id: `AC-${crypto.randomUUID().slice(0, 6).toUpperCase()}`,
      name,
      location: String(data.get("location") ?? "").trim(),
      tileWidth,
      tileHeight,
      example: false,
      files: [],
      notes: "",
    })
    setError("")
    onOpenChange(false)
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
                  defaultValue="300"
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
                  defaultValue="600"
                  required
                />
              </Field>
            </div>
            <FieldDescription>
              {t(
                "Use the dimensions on the box label. Projects and files stay in this browser tab and are cleared on reload."
              )}
            </FieldDescription>
            {error && (
              <p role="alert" className="form-error">
                {t(error)}
              </p>
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
  onAdd: (files: File[]) => Promise<void>
  onRemove: (id: string) => void
}) {
  const { t, number } = useI18n()

  const input = useRef<HTMLInputElement>(null)
  const adding = useRef(false)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  async function add(items: File[]) {
    if (adding.current) return
    adding.current = true
    setBusy(true)
    try {
      await onAdd(items)
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
              "Include the work statement, tile box label, and one photo per wall."
            )}
          </DialogDescription>
        </DialogHeader>
        <input
          ref={input}
          type="file"
          accept="image/jpeg,image/png,image/webp,application/pdf"
          multiple
          disabled={busy}
          className="sr-only"
          aria-label={t("Choose evidence files")}
          onChange={(event) => {
            void add(Array.from(event.target.files ?? []))
            event.target.value = ""
          }}
        />
        <button
          className={cn("upload-zone", dragging && "dragging")}
          disabled={busy}
          onClick={() => input.current?.click()}
          onDragOver={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            if (!busy) void add(Array.from(event.dataTransfer.files))
          }}
        >
          <span className="upload-icon">
            <Upload />
          </span>
          <strong>
            {busy ? t("Checking files…") : t("Drop files here, or browse")}
          </strong>
          <span>
            {t("JPG, PNG, WebP or PDF · 20 MB per file · up to 12 files")}
          </span>
        </button>
        <div className="upload-list" aria-live="polite">
          {files.map((item) => (
            <div key={item.id} className="upload-item">
              {item.kind === "photo" ? (
                <Camera size={18} />
              ) : (
                <FileText size={18} />
              )}
              <div>
                <strong>{item.file.name}</strong>
                <span>
                  {number(item.file.size / 1024 / 1024, 2)}{" "}
                  {t("MB · Local file")}
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
          <AlertTitle>{t("Files stay on your device")}</AlertTitle>
          <AlertDescription>
            {t(
              "Live analysis is not connected yet. Adding files prepares an inspection; it does not generate measurements."
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
          <h3 id="test-files-title">{t("Test files")}</h3>
          <p>
            {t("These synthetic files test uploads, not measurement accuracy.")}
          </p>
          <div className="download-buttons">
            <Button variant="outline" asChild>
              <a href="/images/example-bathroom.png" download>
                {t("Download example photo")}
              </a>
            </Button>
            <Button variant="outline" asChild>
              <a href="/test-data/sample-statement.pdf" download>
                {t("Download sample statement")}
              </a>
            </Button>
            <Button variant="outline" asChild>
              <a href="/test-data/tile-label.pdf" download>
                {t("Download tile label")}
              </a>
            </Button>
          </div>
        </section>
      </DialogContent>
    </Dialog>
  )
}
