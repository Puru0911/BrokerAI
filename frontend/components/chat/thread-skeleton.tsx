export function ThreadSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-hidden="true">
      <SkeletonBubble align="start" width="w-[72%]" />
      <SkeletonBubble align="end" width="w-[48%]" />
      <SkeletonBubble align="start" width="w-[64%]" />
      <SkeletonBubble align="end" width="w-[40%]" />
    </div>
  )
}

function SkeletonBubble({
  align,
  width
}: {
  align: "start" | "end"
  width: string
}) {
  return (
    <div className={align === "end" ? "flex justify-end" : "flex justify-start"}>
      <div
        className={[
          "h-16 animate-pulse rounded-3xl bg-line/70",
          align === "end" ? "rounded-br-md" : "rounded-bl-md",
          width
        ].join(" ")}
      />
    </div>
  )
}
