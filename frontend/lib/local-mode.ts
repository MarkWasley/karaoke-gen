/**
 * Local mode detection for karaoke-gen CLI.
 *
 * Local mode skips cloud authentication and uses the local review API. It is
 * therefore enabled automatically only on loopback hosts. For a deliberate
 * LAN/reverse-proxy access, append ?local=1 to the local review URL.
 */

// Ports used by local review servers
const LOCAL_REVIEW_PORTS = ['8000', '8001', '3200', '8764', '8765', '8766', '8767', '8768', '8769', '8770']
// Development/testing ports (Next.js dev server)
const DEV_TESTING_PORTS = ['3000', '3001', '3002']
const ALL_LOCAL_PORTS = [...new Set([...LOCAL_REVIEW_PORTS, ...DEV_TESTING_PORTS])]

/**
 * Check if the frontend is running in local CLI mode.
 *
 * Loopback hosts retain automatic detection. Other hostnames must explicitly
 * opt in with ?local=1, on a known local-review port, and on the /local/ route.
 * This avoids accidentally enabling the unauthenticated local UI on a public
 * hostname just because it contains /local/.
 */
export function isLocalMode(): boolean {
  if (typeof window === 'undefined') return false

  const { hostname, port, hash, pathname, search } = window.location

  // Hash-based routing belongs to cloud mode.
  if (hash && hash.startsWith('#/')) return false

  const isLoopback = hostname === 'localhost' || hostname === '127.0.0.1'
  if (isLoopback) {
    if (pathname.includes('/local/')) return true
    return ALL_LOCAL_PORTS.includes(port)
  }

  // Explicit opt-in is required when accessing through a LAN/reverse-proxy host.
  const params = new URLSearchParams(search)
  return (
    params.get('local') === '1' &&
    ALL_LOCAL_PORTS.includes(port) &&
    /^\/(?:[a-z]{2}\/)?app\/jobs\/local\/(?:review|instrumental|audio-edit)\/?$/.test(pathname)
  )
}

/**
 * Get the local job ID (always "local" in local mode)
 */
export function getLocalJobId(): string {
  return 'local'
}

/**
 * Check if running in local review mode
 */
export function isLocalReview(): boolean {
  return isLocalMode()
}

/**
 * Mock user object for local mode (no auth required)
 */
export const LOCAL_MODE_USER = {
  email: 'local@localhost',
  role: 'admin' as const,
  credits: 999,
  display_name: 'Local User',
  total_jobs_created: 0,
  total_jobs_completed: 0,
}

/**
 * Mock job object for local mode
 */
export function createLocalModeJob(options: {
  routeType: 'review' | 'instrumental' | 'audio-edit'
  artist?: string
  title?: string
}) {
  return {
    job_id: 'local',
    status: 'awaiting_review',
    progress: 50,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    artist: options.artist || 'Local Artist',
    title: options.title || 'Local Title',
    user_email: 'local@localhost',
    audio_hash: 'local',
  }
}
