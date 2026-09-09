/** Receive an OAuth redirect on the machine running the terminal, including remote gateways. */
export function listenForSetupCallback(authorizationUrl: string, complete: (url: string) => void): () => void {
  const authorization = new URL(authorizationUrl)
  const redirect = new URL(authorization.searchParams.get("redirect_uri") || "")
  const state = authorization.searchParams.get("state")
  if (redirect.protocol !== "http:" || !["localhost", "127.0.0.1"].includes(redirect.hostname)
    || redirect.port !== "1455" || redirect.pathname !== "/auth/callback" || !state) {
    throw new Error("Use the manual callback option for this provider.")
  }
  let submitted = false
  const server = Bun.serve({
    hostname: "127.0.0.1", port: 1455,
    fetch(request) {
      const url = new URL(request.url)
      if (request.method !== "GET" || url.pathname !== redirect.pathname) return new Response("Not found", { status: 404 })
      if (url.searchParams.get("state") !== state) return new Response("Invalid sign-in session", { status: 400 })
      if (!url.searchParams.has("code") && !url.searchParams.has("error")) return new Response("Missing authorization result", { status: 400 })
      if (!submitted) {
        submitted = true
        complete(`${redirect.origin}${redirect.pathname}${url.search}`)
      }
      return new Response("You can return to nanobot. Sign-in is being checked.", {
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" },
      })
    },
  })
  return () => { server.stop(true) }
}
