"use client"

import {
  FormEvent,
  KeyboardEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState
} from "react"

import { IconLink, IconPaperclip, IconSend, IconX } from "@/components/icons"
import { cn } from "@/lib/cn"

type ChatComposerProps = {
  value: string
  disabled: boolean
  busy: boolean
  onChange: (value: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  files: File[]
  onFilesChange: (files: File[]) => void
  link: string
  onLinkChange: (value: string) => void
}

const TEXTAREA_MAX_HEIGHT = 192

export function ChatComposer({
  value,
  disabled,
  busy,
  onChange,
  onSubmit,
  files,
  onFilesChange,
  link,
  onLinkChange
}: ChatComposerProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const [linkOpen, setLinkOpen] = useState(false)
  const canSend =
    Boolean(value.trim() || files.length || link.trim()) && !disabled && !busy

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "0px"
    el.style.height = `${Math.min(el.scrollHeight, TEXTAREA_MAX_HEIGHT)}px`
  }, [value])

  function addFiles(list: FileList | null) {
    if (!list?.length) return
    onFilesChange([...files, ...Array.from(list)].slice(0, 5))
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      if (canSend) {
        event.currentTarget.form?.requestSubmit()
      }
    }
  }

  return (
    <form className="mx-auto w-full max-w-2xl" onSubmit={onSubmit}>
      <div className="rounded-2xl border border-line bg-surface p-2 shadow-composer">
        {files.length > 0 ? (
          <div className="flex flex-wrap gap-2 px-2 pb-2 pt-1">
            {files.map((file, index) => (
              <span
                key={`${file.name}-${index}`}
                className="inline-flex max-w-full items-center gap-2 rounded-full bg-canvas px-3 py-1 text-xs text-ink"
              >
                <span className="min-w-0 truncate">{file.name}</span>
                <button
                  type="button"
                  aria-label={`Remove ${file.name}`}
                  onClick={() =>
                    onFilesChange(
                      files.filter((_, itemIndex) => itemIndex !== index)
                    )
                  }
                  className="text-muted transition hover:text-ink"
                >
                  <IconX />
                </button>
              </span>
            ))}
          </div>
        ) : null}

        {linkOpen ? (
          <input
            value={link}
            onChange={(event) => onLinkChange(event.target.value)}
            disabled={disabled}
            placeholder="Paste a link"
            className="mb-2 w-full min-w-0 rounded-xl bg-canvas px-3 py-2 text-sm text-ink outline-none transition placeholder:text-muted/70 focus:ring-2 focus:ring-accent/20 disabled:text-muted"
          />
        ) : null}

        <div className="flex items-end gap-1">
          <input
            ref={fileInputRef}
            type="file"
            className="sr-only"
            multiple
            accept="image/jpeg,image/png,image/webp,image/heic,.pdf,.docx"
            onChange={(event) => {
              addFiles(event.target.files)
              event.target.value = ""
            }}
          />
          <IconButton
            label="Attach a file"
            disabled={disabled}
            onClick={() => fileInputRef.current?.click()}
          >
            <IconPaperclip />
          </IconButton>
          <label className="sr-only" htmlFor="message">
            Message
          </label>
          <textarea
            id="message"
            ref={textareaRef}
            value={value}
            rows={1}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            placeholder="Describe what you need, or attach a file…"
            className="max-h-48 min-h-11 min-w-0 flex-1 resize-none bg-transparent px-2 py-2.5 text-sm leading-6 text-ink outline-none placeholder:text-muted/70 disabled:text-muted [overflow-wrap:anywhere] whitespace-pre-wrap break-words"
          />
          <IconButton
            label="Add a link"
            disabled={disabled}
            pressed={linkOpen}
            onClick={() => setLinkOpen((open) => !open)}
          >
            <IconLink />
          </IconButton>
          <button
            type="submit"
            disabled={!canSend}
            aria-label={busy ? "Sending" : "Send"}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-surface transition hover:bg-[#0c4d48] disabled:bg-line disabled:text-muted"
          >
            <IconSend />
          </button>
        </div>
      </div>
      <p className="mt-2 hidden text-center text-[11px] text-muted sm:block">
        Enter to send · Shift + Enter for a new line
      </p>
    </form>
  )
}

function IconButton({
  label,
  disabled,
  pressed,
  onClick,
  children
}: {
  label: string
  disabled: boolean
  pressed?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-muted transition hover:bg-canvas hover:text-ink disabled:opacity-50",
        pressed && "bg-accent-soft text-accent"
      )}
    >
      {children}
    </button>
  )
}
