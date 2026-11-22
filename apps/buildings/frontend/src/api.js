// Thin fetch wrapper. Every failure becomes an ApiError carrying the backend's
// what / where / why / fix so the UI can show an actionable message.
export class ApiError extends Error {
  constructor(info, status) {
    super(info.what || 'Request failed')
    this.info = info
    this.status = status
  }
}

async function call(method, url, body, raw) {
  let res
  try {
    res = await fetch(url, {
      method,
      headers: body !== undefined && !raw ? { 'Content-Type': 'application/json' } : undefined,
      body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
    })
  } catch (e) {
    throw new ApiError({ what: 'Cannot reach the server', where: url, why: String(e.message || e), fix: 'Start the backend (scripts/start.sh) and reload' }, 0)
  }
  if (res.status === 204) return null
  const ct = res.headers.get('content-type') || ''
  const data = ct.includes('json') ? await res.json() : await res.text()
  if (!res.ok) {
    const info = (data && data.error) || { what: `HTTP ${res.status}`, where: url, why: typeof data === 'string' ? data.slice(0, 200) : '', fix: '' }
    throw new ApiError(info, res.status)
  }
  return data
}

export const api = {
  health: () => call('GET', '/api/health'),
  system: () => call('GET', '/api/system'),
  perf: (limit = 50) => call('GET', `/api/perf?limit=${limit}`),
  listProjects: () => call('GET', '/api/projects'),
  createProject: (name, units) => call('POST', '/api/projects', { name, units }),
  getProject: (id) => call('GET', `/api/projects/${id}`),
  putProject: (p) => call('PUT', `/api/projects/${p.id}`, p),
  deleteProject: (id) => call('DELETE', `/api/projects/${id}`),
  backups: (id) => call('GET', `/api/projects/${id}/backups`),
  makeBackup: (id) => call('POST', `/api/projects/${id}/backups`),
  restoreBackup: (id, name) => call('POST', `/api/projects/${id}/backups/${encodeURIComponent(name)}/restore`),
  deleteBackup: (id, name) => call('DELETE', `/api/projects/${id}/backups/${encodeURIComponent(name)}`),
  modules: (id) => call('GET', `/api/modules/${id}`),
  validate: (project_id) => call('POST', '/api/geometry/validate', { project_id }),
  submit: (path, body) => call('POST', path, body),
  status: (jid) => call('GET', `/api/build/status/${jid}`),
  result: (jid) => call('GET', `/api/build/result/${jid}`),
  cancel: (jid) => call('POST', `/api/build/cancel/${jid}`),
  textures: (id) => call('GET', `/api/projects/${id}/textures`),
  putTexture: (id, file) => call('PUT', `/api/projects/${id}/textures/${encodeURIComponent(file.name)}`, file, true),
  deleteTexture: (id, name) => call('DELETE', `/api/projects/${id}/textures/${encodeURIComponent(name)}`),
  fileUrl: (id, path) => `/api/projects/${id}/files/${path}`,
}

export const formatError = (e) =>
  e && e.info ? e.info : { what: String((e && e.message) || e), where: '', why: '', fix: '' }
