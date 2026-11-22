// Browser-side preparation of a scanned plan: PDF page / big image -> PNG or JPEG small enough to upload.
const MAX_SIDE = 3500
const MAX_BYTES = 11 * 1024 * 1024

const toBlob = (canvas, type, q) => new Promise((res) => canvas.toBlob(res, type, q))

async function encode(canvas, preferPng) {
  let blob = preferPng ? await toBlob(canvas, 'image/png') : null
  if (!blob || blob.size > MAX_BYTES) blob = await toBlob(canvas, 'image/jpeg', 0.9)
  if (blob.size > MAX_BYTES) blob = await toBlob(canvas, 'image/jpeg', 0.75)
  return blob
}

function fitCanvas(w, h) {
  const k = Math.min(1, MAX_SIDE / Math.max(w, h))
  const c = document.createElement('canvas')
  c.width = Math.max(1, Math.round(w * k)); c.height = Math.max(1, Math.round(h * k))
  return c
}

/** PDF: number of pages (cheap) and a renderer for one page. */
export async function openPdf(file) {
  const pdfjs = await import('pdfjs-dist')
  const worker = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
  pdfjs.GlobalWorkerOptions.workerSrc = worker
  const doc = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise
  return {
    pages: doc.numPages,
    async render(n) {
      const page = await doc.getPage(Math.min(Math.max(1, n), doc.numPages))
      const v1 = page.getViewport({ scale: 1 })
      const k = MAX_SIDE / Math.max(v1.width, v1.height)
      const vp = page.getViewport({ scale: k })
      const c = document.createElement('canvas'); c.width = Math.round(vp.width); c.height = Math.round(vp.height)
      const ctx = c.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, c.width, c.height)
      await page.render({ canvasContext: ctx, viewport: vp }).promise
      return { blob: await encode(c, false), w: c.width, h: c.height }
    },
  }
}

/** PNG / JPEG: downscale if needed. Returns {blob, w, h}. */
export async function prepareImage(file) {
  const bmp = await createImageBitmap(file)
  const c = fitCanvas(bmp.width, bmp.height)
  c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height)
  const small = c.width === bmp.width && file.size <= MAX_BYTES
  return { blob: small ? file : await encode(c, /png/i.test(file.type)), w: c.width, h: c.height }
}

export const uploadUnderlay = async (pid, name, blob) => {
  const r = await fetch(`/api/projects/${pid}/underlays/${encodeURIComponent(name)}`, { method: 'PUT', body: blob, headers: { 'content-type': blob.type || 'application/octet-stream' } })
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).error?.why || m } catch { /* keep status text */ } throw new Error(m) }
}
export const deleteUnderlayFile = (pid, name) => fetch(`/api/projects/${pid}/underlays/${encodeURIComponent(name)}`, { method: 'DELETE' }).catch(() => {})
export const underlayUrl = (pid, file, v = '') => `/api/projects/${pid}/files/underlays/${encodeURIComponent(file)}${v ? '?v=' + v : ''}`
