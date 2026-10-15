import type { ReactNode } from "react"

const BOLD_MARK = /\*\*(.+?)\*\*/g

export function ChatText({ text }: { text: string }) {
  return <>{renderBoldMarks(text)}</>
}

function renderBoldMarks(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let cursor = 0
  for (const match of text.matchAll(BOLD_MARK)) {
    const start = match.index ?? 0
    if (start > cursor) {
      nodes.push(text.slice(cursor, start))
    }
    nodes.push(
      <strong key={start} className="font-semibold">
        {match[1]}
      </strong>
    )
    cursor = start + match[0].length
  }
  if (cursor < text.length) {
    nodes.push(text.slice(cursor))
  }
  return nodes
}
