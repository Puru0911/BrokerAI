export function BackendUnavailable({ message }: { message: string }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f6faf9] px-5 py-10">
      <section className="w-full max-w-md rounded-md border border-slate-200 bg-white p-6 text-center shadow-sm sm:p-8">
        <h1 className="text-2xl font-semibold text-[#10275b]">
          Backend connection needed
        </h1>
        <p className="mt-3 text-sm leading-6 text-slate-600">{message}</p>
        <div className="mt-5 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700">
          Start FastAPI, then refresh this page.
        </div>
      </section>
    </main>
  )
}
