/**
 * Hostnames that mean "this page is served by a local stack, not production": a developer's
 * `next dev`, gen's scripts/local-stack.sh, and nomad-mobile's E2E, which loads gen web in an
 * emulator's Chrome (127.0.0.1 through adb reverse, or 10.0.2.2, the Android emulator's alias for
 * the host machine). Pages on these hosts must never talk to production services: API calls go
 * relative (lib/api.ts API_BASE_URL) and Google Analytics is not loaded.
 */
export const LOCAL_HOSTNAMES: readonly string[] = ['localhost', '127.0.0.1', '10.0.2.2']

const LOCAL_REVIEW_PORTS = new Set([
  '8000', '8001', '3200', '8764', '8765', '8766', '8767', '8768', '8769', '8770',
])

export function isLocalHostname(hostname: string | null | undefined): boolean {
  return !!hostname && LOCAL_HOSTNAMES.includes(hostname)
}

/**
 * The standalone karaoke-gen review UI can deliberately be opened through a LAN
 * hostname/reverse proxy using ?local=1. That opt-in must select the same-origin
 * local API too; otherwise the page renders in local mode but sends its data
 * requests to the production API, which then rejects the local job for lacking
 * a cloud review token.
 */
function isExplicitLocalReviewUrl(): boolean {
  if (typeof window === 'undefined') return false
  const { search, pathname, port, hash } = window.location
  if (hash && hash.startsWith('#/')) return false
  if (!LOCAL_REVIEW_PORTS.has(port)) return false
  if (new URLSearchParams(search).get('local') !== '1') return false
  return /^\/(?:[a-z]{2}\/)?app\/jobs\/local\/(?:review|instrumental|audio-edit)\/?$/.test(pathname)
}

/** True in a browser whose page host is local. False during SSR / static export. */
export function isLocalPage(): boolean {
  return typeof window !== 'undefined' &&
    (isLocalHostname(window.location?.hostname) || isExplicitLocalReviewUrl())
}

/**
 * A local page's `?baseApiUrl=` override (pointing the page at another local stack, e.g. another E2E
 * lane's gen), only when it is an http(s) URL on a local host. Anything else is ignored (''), so
 * a crafted link can't send the page's bearer token to another origin.
 */
export function localApiOverride(search: string): string {
  const raw = new URLSearchParams(search).get('baseApiUrl')
  if (!raw) return ''
  try {
    const url = new URL(raw)
    return (url.protocol === 'http:' || url.protocol === 'https:') && isLocalHostname(url.hostname)
      ? raw.replace(/\/+$/, '')
      : ''
  } catch {
    return ''
  }
}
