import { BrandMark } from "@/components/brand/mark"
import { AGENT_NAME, welcomeMessage } from "@/lib/agent"
import { cn } from "@/lib/cn"

function BrokerBubble({ children }: { children: string }) {
  return (
    <div className="flex max-w-[92%] items-end gap-2">
      <BrandMark size={22} title="" />
      <div className="rounded-2xl rounded-bl-md border border-line bg-surface px-3.5 py-2.5 text-[13px] leading-5 text-ink shadow-sm">
        {children}
      </div>
    </div>
  )
}

function UserBubble({ children }: { children: string }) {
  return (
    <div className="ml-auto max-w-[86%] rounded-2xl rounded-br-md bg-user px-3.5 py-2.5 text-[13px] leading-5 text-surface">
      {children}
    </div>
  )
}

export function ProductPreview({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-[1.6rem] border border-white/20 bg-surface shadow-[0_28px_80px_-24px_rgba(15,92,86,0.45)] ring-1 ring-black/5",
        className
      )}
      aria-hidden="true"
    >
      <div className="flex items-center gap-2 border-b border-line bg-canvas/80 px-4 py-3">
        <span className="h-2.5 w-2.5 rounded-full bg-[#E8C4B8]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#E6D7A8]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#B7D3C8]" />
        <div className="ml-2 text-xs font-medium text-muted">{AGENT_NAME}</div>
      </div>
      <div className="grid min-h-[22rem] grid-cols-1 sm:grid-cols-[9.5rem_minmax(0,1fr)]">
        <aside className="hidden border-r border-line bg-canvas px-3 py-3 sm:block">
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted">
            Requests
          </div>
          <div className="mt-3 space-y-2">
            <div className="rounded-xl bg-accent px-2.5 py-2 text-[11px] font-medium leading-4 text-surface">
              Your request
            </div>
            <div className="rounded-xl px-2.5 py-2 text-[11px] leading-4 text-muted">
              Earlier brief
            </div>
            <div className="rounded-xl px-2.5 py-2 text-[11px] leading-4 text-muted">
              Closed intro
            </div>
          </div>
        </aside>
        <div className="flex flex-col bg-canvas/40 px-3 py-4 sm:px-4">
          <div className="space-y-3">
            <BrokerBubble>{welcomeMessage()}</BrokerBubble>
            <UserBubble>
              I need to find the right person for this. I’ll explain as we go.
            </UserBubble>
            <BrokerBubble>
              Say it in your own words. I’ll look quietly, and only bring someone
              forward when both of you can help each other.
            </BrokerBubble>
            <div className="rounded-2xl border border-line bg-surface p-3 shadow-sm">
              <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-accent">
                Strong fit
              </div>
              <p className="mt-1.5 text-[13px] font-medium leading-5 text-ink">
                A counterpart whose brief lines up with yours.
              </p>
              <p className="mt-1 text-[12px] leading-5 text-muted">
                Identity stays private until you both agree.
              </p>
              <div className="mt-3 flex gap-2">
                <span className="inline-flex h-8 flex-1 items-center justify-center rounded-lg bg-accent text-[11px] font-semibold text-surface">
                  Interested
                </span>
                <span className="inline-flex h-8 flex-1 items-center justify-center rounded-lg border border-line text-[11px] font-semibold text-ink">
                  Skip
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
