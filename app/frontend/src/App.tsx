import { useI18n, type Locale } from "@/lib/i18n"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { useEffect, useRef, useState } from "react"
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Camera,
  Check,
  CircleHelp,
  Download,
  FileText,
  FolderOpen,
  Grid2X2,
  Info,
  MessageSquareText,
  Moon,
  Plus,
  Ruler,
  Sun,
  Upload,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Textarea } from "@/components/ui/textarea"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "@/components/ui/empty"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { EvidenceViewer } from "@/features/inspection/evidence"
import { StatementReview } from "@/features/inspection/review"
import {
  CaptureGuide,
  NewProjectDialog,
  UploadDialog,
} from "@/features/inspection/project-dialogs"
import { ReportDialog } from "@/features/inspection/report"
import {
  exampleProject,
  type LocalFile,
  type Project,
} from "@/features/inspection/data"

type Section = "evidence" | "review" | "report"
function Notes({
  project,
  onSave,
}: {
  project: Project
  onSave: (notes: string) => void
}) {
  const { t } = useI18n()

  const [edited, setEdited] = useState<string | null>(null)
  const savedNotes =
    project.example && project.notes === exampleProject.notes
      ? t(project.notes)
      : project.notes
  const value = edited ?? savedNotes
  return (
    <section className="panel notes-panel">
      <div className="panel-heading">
        <div>
          <h2>{t("Review notes")}</h2>
          <span className="subtle">
            {t("Keep questions and site observations together.")}
          </span>
        </div>
        <MessageSquareText size={20} />
      </div>
      <form
        className="notes-form"
        onSubmit={(event) => {
          event.preventDefault()
          onSave(value)
          setEdited(null)
          toast.success(t("Notes saved for this session"))
        }}
      >
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="review-notes">
              {t("Your observations")}
            </FieldLabel>
            <Textarea
              id="review-notes"
              value={value}
              onChange={(event) => setEdited(event.target.value)}
              rows={7}
              maxLength={5000}
              placeholder={t(
                "Add an observation or a question for the contractor…"
              )}
            />
          </Field>
        </FieldGroup>
        <div className="notes-footer">
          <span>{t("Saved in this tab · included in exported reports")}</span>
          <Button type="submit" disabled={value === savedNotes}>
            {t("Save notes")}
          </Button>
        </div>
      </form>
    </section>
  )
}

function App() {
  const { t, number, locale, setLocale, theme, setTheme } = useI18n()
  const [projects, setProjects] = useState<Project[]>([exampleProject])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [section, setSection] = useState<Section>("evidence")
  const [newOpen, setNewOpen] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [guideOpen, setGuideOpen] = useState(false)
  const [reportOpen, setReportOpen] = useState(false)
  const [preview, setPreview] = useState<LocalFile | null>(null)
  const urls = useRef(new Set<string>())
  const headingRef = useRef<HTMLHeadingElement>(null)
  const hasMounted = useRef(false)
  useEffect(() => {
    if (!hasMounted.current) {
      hasMounted.current = true
      return
    }
    const frame = requestAnimationFrame(() => headingRef.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [activeId])
  function goToSection(next: Section) {
    setSection(next)
    requestAnimationFrame(() =>
      document
        .querySelector<HTMLElement>('.journey-list [data-state="active"]')
        ?.focus()
    )
  }
  const project =
    projects.find((item) => item.id === activeId) ?? exampleProject
  const ownProjects = projects.filter((item) => !item.example)
  useEffect(() => {
    const heldUrls = urls.current
    return () => heldUrls.forEach((url) => URL.revokeObjectURL(url))
  }, [])
  function selectProject(id: string) {
    setActiveId(id)
    setSection("evidence")
  }
  function updateProject(update: (item: Project) => Project) {
    setProjects((items) =>
      items.map((item) => (item.id === activeId ? update(item) : item))
    )
  }
  function createProject(item: Project) {
    setProjects((items) => [...items, item])
    selectProject(item.id)
    toast.success(t("Inspection created"))
  }
  function removeFile(id: string) {
    const found = project.files.find((item) => item.id === id)
    if (found) {
      URL.revokeObjectURL(found.url)
      urls.current.delete(found.url)
    }
    updateProject((item) => ({
      ...item,
      files: item.files.filter((file) => file.id !== id),
    }))
  }
  async function addFiles(incoming: File[]) {
    const accepted: LocalFile[] = []
    for (const file of incoming) {
      if (project.files.length + accepted.length >= 12) {
        toast.error(t("An inspection can hold up to 12 files."))
        break
      }
      if (
        !["image/jpeg", "image/png", "image/webp", "application/pdf"].includes(
          file.type
        )
      ) {
        toast.error(
          t("{name}: use JPG, PNG, WebP or PDF.", { name: file.name })
        )
        continue
      }
      if (file.size === 0 || file.size > 20 * 1024 * 1024) {
        toast.error(
          t("{name}: choose a nonempty file under 20 MB.", { name: file.name })
        )
        continue
      }
      if (
        [...project.files, ...accepted].some(
          (item) =>
            item.file.name === file.name &&
            item.file.size === file.size &&
            item.file.lastModified === file.lastModified
        )
      ) {
        toast.info(t("{name} is already added.", { name: file.name }))
        continue
      }
      const url = URL.createObjectURL(file)
      const kind = file.type === "application/pdf" ? "document" : "photo"
      try {
        if (kind === "photo")
          await new Promise<void>((resolve, reject) => {
            const img = new Image()
            img.onload = () => resolve()
            img.onerror = () => reject(new Error("Unreadable image"))
            img.src = url
          })
        else if (!(await file.slice(0, 5).text()).startsWith("%PDF-"))
          throw new Error("Unreadable PDF")
        accepted.push({ id: crypto.randomUUID(), file, url, kind })
        urls.current.add(url)
      } catch {
        URL.revokeObjectURL(url)
        toast.error(
          t("{name} could not be read. Choose another file.", {
            name: file.name,
          })
        )
      }
    }
    if (accepted.length) {
      updateProject((item) => ({
        ...item,
        files: [...item.files, ...accepted],
      }))
      toast.success(
        t("Files added locally: {count}", { count: number(accepted.length) })
      )
    }
  }

  function evidenceFiles() {
    return (
      <section className="evidence-files" aria-labelledby="files-title">
        <div className="section-heading">
          <div>
            <h2 id="files-title">{t("Project evidence")}</h2>
            <p>{t("Statements, reference material, and room photos.")}</p>
          </div>
          {!project.example && (
            <Button onClick={() => setUploadOpen(true)}>
              <Upload data-icon="inline-start" />
              {t("Add files")}
            </Button>
          )}
        </div>
        {project.example ? (
          <div className="dossier-files">
            <a
              href="/test-data/sample-statement.pdf"
              download
              className="dossier-file"
            >
              <FileText />
              <span>
                <strong>{t("Contractor statement")}</strong>
                <small>{t("5 line items · example document")}</small>
              </span>
              <span className="file-action">
                PDF <Download size={16} />
              </span>
            </a>
            <a
              href="/test-data/tile-label.pdf"
              download
              className="dossier-file"
            >
              <Grid2X2 />
              <span>
                <strong>{t("Ceramic tile specification")}</strong>
                <small>
                  {t("300 × 600 mm · 2 mm grout · example reference")}
                </small>
              </span>
              <span className="file-action">
                PDF <Download size={16} />
              </span>
            </a>
            <a
              href="/images/example-bathroom.png"
              download
              className="dossier-file"
            >
              <Camera />
              <span>
                <strong>{t("Room evidence")}</strong>
                <small>
                  {t("4 sample wall records · shared synthetic illustration")}
                </small>
              </span>
              <span className="file-action">
                PNG <Download size={16} />
              </span>
            </a>
          </div>
        ) : project.files.length ? (
          <div className="dossier-files">
            {project.files.map((item) => (
              <div key={item.id} className="attachment-line">
                <button
                  className="dossier-file"
                  onClick={() => setPreview(item)}
                >
                  {item.kind === "photo" ? (
                    <img src={item.url} alt="" />
                  ) : (
                    <FileText />
                  )}
                  <span>
                    <strong>{item.file.name}</strong>
                    <small>
                      {number(item.file.size / 1024 / 1024, 2)}{" "}
                      {t("MB · Not analysed")}
                    </small>
                  </span>
                  <span className="file-action">
                    {t("Preview file")}
                    <ArrowUpRight size={16} />
                  </span>
                </button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => removeFile(item.id)}
                  aria-label={t("Remove {name}", { name: item.file.name })}
                >
                  {t("Remove")}
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <div className="upload-start">
            <Upload aria-hidden="true" />
            <p>{t("No files added yet.")}</p>
            <span>
              {t("JPG, PNG, WebP or PDF · up to 20 MB each · 12 files maximum")}
            </span>
          </div>
        )}
      </section>
    )
  }
  return (
    <TooltipProvider>
      <div className="app-shell workbench">
        <a href="#main-content" className="skip-link">
          {t("Skip to inspection")}
        </a>
        <header className="workbench-header">
          <button
            className="wordmark"
            onClick={() => setActiveId(null)}
            aria-label={t("ActCheck home")}
          >
            <span className="wordmark-symbol" aria-hidden="true">
              <Check size={19} />
            </span>
            ActCheck
          </button>
          <div className="header-divider" aria-hidden="true" />
          <span className="product-label">{t("Renovation inspections")}</span>
          <div className="topbar-actions">
            <Field className="language-field">
              <FieldLabel className="sr-only" htmlFor="language-select">
                {t("Language")}
              </FieldLabel>
              <NativeSelect
                id="language-select"
                value={locale}
                onChange={(event) => setLocale(event.target.value as Locale)}
              >
                <NativeSelectOption value="en" lang="en">
                  English
                </NativeSelectOption>
                <NativeSelectOption value="kk" lang="kk">
                  Қазақша
                </NativeSelectOption>
                <NativeSelectOption value="ru" lang="ru">
                  Русский
                </NativeSelectOption>
              </NativeSelect>
            </Field>
            <Button
              variant="ghost"
              size="icon"
              title={t(theme === "dark" ? "Light" : "Dark")}
              aria-label={
                t("Appearance") + ": " + t(theme === "dark" ? "Light" : "Dark")
              }
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
            <Button
              variant="ghost"
              className="header-help"
              onClick={() => setGuideOpen(true)}
            >
              <CircleHelp data-icon="inline-start" />
              {t("Help & guidance")}
            </Button>
          </div>
        </header>
        <main id="main-content" className="workbench-main">
          {activeId === null ? (
            <>
              <div className="register-heading">
                <div>
                  <span className="section-kicker">
                    {t("INSPECTION REGISTER")}
                  </span>
                  <h1 ref={headingRef} tabIndex={-1}>
                    {t("Your inspections")}
                  </h1>
                  <p>
                    {t(
                      "Bring the statement, tile size and room photos together."
                    )}
                  </p>
                </div>
                <Button size="lg" onClick={() => setNewOpen(true)}>
                  <Plus data-icon="inline-start" />
                  {t("New inspection")}
                </Button>
              </div>
              <section className="start-brief" aria-labelledby="start-title">
                <div className="brief-title">
                  <h2 id="start-title">
                    {t("A clear path from evidence to questions.")}
                  </h2>
                  <p>
                    {t(
                      "Start with one room. Keep its documents and observations in one place."
                    )}
                  </p>
                </div>
                <ol className="workflow-intro">
                  <li>
                    <span className="step-index">01</span>
                    <h3>{t("Gather evidence")}</h3>
                    <p>
                      {t(
                        "Add the work statement, tile dimensions and wall photos."
                      )}
                    </p>
                  </li>
                  <li>
                    <span className="step-index">02</span>
                    <h3>{t("Review quantities")}</h3>
                    <p>
                      {t(
                        "Compare each work item and see what still needs proof."
                      )}
                    </p>
                  </li>
                  <li>
                    <span className="step-index">03</span>
                    <h3>{t("Prepare your questions")}</h3>
                    <p>
                      {t(
                        "Record observations and export a report for your contractor."
                      )}
                    </p>
                  </li>
                </ol>
              </section>
              <div className="register-section-title">
                <h2>{t("Your work")}</h2>
                <span>{t("This browser session")}</span>
              </div>
              {ownProjects.length ? (
                <div className="inspection-register">
                  {ownProjects.map((item) => (
                    <button
                      key={item.id}
                      className="register-row"
                      onClick={() => selectProject(item.id)}
                    >
                      <FolderOpen />
                      <span className="register-name">
                        <strong>{item.name}</strong>
                        <small>
                          {item.location || t("Location not specified")}
                        </small>
                      </span>
                      <Badge variant="outline">{t("Draft")}</Badge>
                      <span className="register-file-count">
                        {t("Files: {count}", {
                          count: number(item.files.length),
                        })}
                      </span>
                      <ArrowRight />
                    </button>
                  ))}
                </div>
              ) : (
                <div className="register-empty">
                  <FolderOpen />
                  <div>
                    <h3>{t("No inspections yet")}</h3>
                    <p>
                      {t(
                        "Create an inspection to collect your own evidence, or explore the worked example below."
                      )}
                    </p>
                  </div>
                </div>
              )}
              <section className="worked-example">
                <img src="/images/example-bathroom.png" alt="" />
                <div>
                  <span className="section-kicker">{t("WORKED EXAMPLE")}</span>
                  <h2>{t("Bathroom renovation")}</h2>
                  <p>
                    {t(
                      "Follow a sample inspection from files to contractor questions. All quantities are illustrative."
                    )}
                  </p>
                </div>
                <Button
                  variant="outline"
                  onClick={() => selectProject(exampleProject.id)}
                >
                  {t("Explore example")}
                  <ArrowRight data-icon="inline-end" />
                </Button>
              </section>
              <p className="session-note">
                <Info size={15} />
                {t(
                  "This prototype keeps your work in this tab only. Export before closing or reloading."
                )}
              </p>
            </>
          ) : (
            <>
              <Button
                variant="ghost"
                className="back-to-register"
                onClick={() => setActiveId(null)}
              >
                <ArrowLeft data-icon="inline-start" />
                {t("All inspections")}
              </Button>
              <div className="inspection-heading">
                <div>
                  <div className="heading-meta">
                    <span className="section-kicker">{project.id}</span>
                    <Badge variant="outline">
                      {project.example ? t("Worked example") : t("Draft")}
                    </Badge>
                  </div>
                  <h1 ref={headingRef} tabIndex={-1}>
                    {project.example ? t(project.name) : project.name}
                  </h1>
                  <p>
                    {project.example
                      ? t(project.location)
                      : project.location || t("Location not specified")}
                  </p>
                </div>
                <dl className="inspection-reference">
                  <dt>{t("Reference tile")}</dt>
                  <dd>
                    {number(project.tileWidth)} × {number(project.tileHeight)}{" "}
                    {t("mm")}
                  </dd>
                </dl>
              </div>
              {project.example && (
                <div className="sample-notice">
                  <Info size={16} />
                  <p>
                    {t(
                      "You are viewing a worked example. Photos and measurements are synthetic."
                    )}
                  </p>
                  <button onClick={() => setNewOpen(true)}>
                    {t("Start your own")}
                    <ArrowRight size={15} />
                  </button>
                </div>
              )}
              <Tabs
                value={section}
                onValueChange={(value) => setSection(value as Section)}
                className="journey-tabs"
              >
                <TabsList
                  variant="line"
                  className="journey-list"
                  aria-label={t("Inspection sections")}
                >
                  <TabsTrigger value="evidence">
                    <span className="journey-number">1</span>
                    {t("Gather evidence")}
                  </TabsTrigger>
                  <TabsTrigger value="review">
                    <span className="journey-number">2</span>
                    {t("Review quantities")}
                  </TabsTrigger>
                  <TabsTrigger value="report">
                    <span className="journey-number">3</span>
                    {t("Notes & report")}
                  </TabsTrigger>
                </TabsList>
                <TabsContent value="evidence">
                  <div className="evidence-workspace">
                    <div>{evidenceFiles()}</div>
                    <aside className="evidence-checklist">
                      <h2>{t("What you need")}</h2>
                      <ul>
                        <li>
                          <FileText />
                          <div>
                            <strong>{t("Work statement")}</strong>
                            <p>{t("Include quantities, units and prices.")}</p>
                          </div>
                        </li>
                        <li>
                          <Grid2X2 />
                          <div>
                            <strong>{t("Tile box label")}</strong>
                            <p>
                              {t(
                                "Use the printed width and height in millimetres."
                              )}
                            </p>
                          </div>
                        </li>
                        <li>
                          <Camera />
                          <div>
                            <strong>{t("One photo per wall")}</strong>
                            <p>
                              {t(
                                "Keep the whole tiled surface and its edges visible."
                              )}
                            </p>
                          </div>
                        </li>
                      </ul>
                      <Button
                        variant="outline"
                        onClick={() => setGuideOpen(true)}
                      >
                        {t("Photo tips & test files")}
                        <ArrowUpRight data-icon="inline-end" />
                      </Button>
                    </aside>
                  </div>
                  {!project.example && (
                    <Alert className="availability-notice">
                      <Info />
                      <AlertTitle>
                        {t("Automatic analysis is not available yet")}
                      </AlertTitle>
                      <AlertDescription>
                        {t(
                          "You can collect files and write notes. Measurements require the analysis service; uploading files does not produce results."
                        )}
                      </AlertDescription>
                    </Alert>
                  )}
                  <div className="section-next">
                    <p>
                      {project.example
                        ? t(
                            "Next, compare the statement with the sample measurements."
                          )
                        : t(
                            "Files stay in this browser tab. Reloading clears your uploads."
                          )}
                    </p>
                    <Button
                      onClick={() =>
                        goToSection(project.example ? "review" : "report")
                      }
                    >
                      {project.example
                        ? t("Review quantities")
                        : t("Continue to notes")}
                      <ArrowRight data-icon="inline-end" />
                    </Button>
                  </div>
                </TabsContent>
                <TabsContent value="review">
                  {project.example ? (
                    <>
                      <div className="review-context">
                        <div>
                          <span className="section-kicker">
                            {t("REVIEW THE STATEMENT")}
                          </span>
                          <h2>{t("Which quantities need a second look?")}</h2>
                          <p>
                            {t(
                              "2 items need review. 2 hidden-work items require supporting records."
                            )}
                          </p>
                        </div>
                        <div className="review-amount">
                          <span>{t("Wall tiling amount to clarify")}</span>
                          <strong>
                            {number(99750)} <small>₸</small>
                          </strong>
                          <p>{t("At least · using the upper area bound")}</p>
                        </div>
                      </div>
                      <StatementReview />
                      <details className="supporting-evidence">
                        <summary>
                          <Ruler size={18} />
                          <span>
                            {t("Inspect the wall measurements")}
                            <small>
                              {t(
                                "See the image, tile reference and uncertainty behind the sample quantities."
                              )}
                            </small>
                          </span>
                          <Plus size={18} />
                        </summary>
                        <EvidenceViewer />
                      </details>
                      <div className="section-next">
                        <p>
                          {t(
                            "Keep the questions that matter, then prepare your report."
                          )}
                        </p>
                        <Button onClick={() => goToSection("report")}>
                          {t("Notes & report")}
                          <ArrowRight data-icon="inline-end" />
                        </Button>
                      </div>
                    </>
                  ) : (
                    <Empty className="analysis-empty">
                      <EmptyHeader>
                        <EmptyTitle>{t("No measurements yet")}</EmptyTitle>
                        <EmptyDescription>
                          {t(
                            "Automatic analysis is not available yet. Your files have not been measured or compared with the statement."
                          )}
                        </EmptyDescription>
                      </EmptyHeader>
                      <EmptyContent>
                        <Button onClick={() => goToSection("evidence")}>
                          {t("Back to evidence")}
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => selectProject(exampleProject.id)}
                        >
                          {t("Open example inspection")}
                        </Button>
                      </EmptyContent>
                    </Empty>
                  )}
                </TabsContent>
                <TabsContent value="report">
                  <div className="report-workspace">
                    <Notes
                      key={project.id}
                      project={project}
                      onSave={(notes) =>
                        updateProject((item) => ({ ...item, notes }))
                      }
                    />
                    <aside className="report-action">
                      <span className="section-kicker">
                        {t("TAKE IT TO THE CONTRACTOR")}
                      </span>
                      <h2>{t("Your inspection report")}</h2>
                      <p>
                        {project.example
                          ? t(
                              "Includes sample quantities, contractor questions and your saved notes."
                            )
                          : t(
                              "Includes your file list and saved notes. No measured quantities are available yet."
                            )}
                      </p>
                      <Button onClick={() => setReportOpen(true)}>
                        <Download data-icon="inline-start" />
                        {t("Preview & export")}
                      </Button>
                      <span>{t("HTML download or print to PDF")}</span>
                    </aside>
                  </div>
                </TabsContent>
              </Tabs>
            </>
          )}
          <footer className="workbench-footer">
            <span>
              ActCheck <span aria-hidden="true">/</span>{" "}
              {t("Renovation inspections")}
            </span>
            <span>{t("Files stay on this device")}</span>
          </footer>
        </main>
        <NewProjectDialog
          open={newOpen}
          onOpenChange={setNewOpen}
          onCreate={createProject}
        />
        <UploadDialog
          open={uploadOpen}
          onOpenChange={setUploadOpen}
          files={project.files}
          onAdd={addFiles}
          onRemove={removeFile}
        />
        <CaptureGuide open={guideOpen} onOpenChange={setGuideOpen} />
        <ReportDialog
          open={reportOpen}
          onOpenChange={setReportOpen}
          project={project}
        />
        <Dialog
          open={preview !== null}
          onOpenChange={(open) => !open && setPreview(null)}
        >
          <DialogContent className="file-preview-dialog">
            <DialogHeader>
              <DialogTitle>{preview?.file.name}</DialogTitle>
              <DialogDescription>
                {t("Local evidence · not analysed")}
              </DialogDescription>
            </DialogHeader>
            {preview?.kind === "photo" ? (
              <img
                className="uploaded-preview"
                src={preview.url}
                alt={preview.file.name}
              />
            ) : (
              preview && (
                <div className="pdf-preview">
                  <FileText size={40} />
                  <p>{t("Your PDF is ready to review.")}</p>
                  <Button asChild>
                    <a
                      href={preview.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {t("Open PDF")}
                      <ArrowUpRight data-icon="inline-end" />
                    </a>
                  </Button>
                </div>
              )
            )}
          </DialogContent>
        </Dialog>
        <Toaster position="bottom-right" richColors theme={theme} />
      </div>
    </TooltipProvider>
  )
}
export default App
