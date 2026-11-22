import { useEffect, useState } from 'react'
import { Image as KImage, Layer } from 'react-konva'
import { underlayHeight } from '../plan.js'
import { underlayUrl } from '../underlay.js'

const cache = new Map()
function useImg(url) {
  const [img, setImg] = useState(cache.get(url) || null)
  useEffect(() => {
    if (cache.has(url)) { setImg(cache.get(url)); return undefined }
    let live = true
    const im = new window.Image()
    im.onload = () => { cache.set(url, im); if (live) setImg(im) }
    im.src = url
    return () => { live = false }
  }, [url])
  return img
}

function One({ u, pid, view }) {
  const img = useImg(underlayUrl(pid, u.file))
  if (!img) return null
  const k = view.scale
  return <KImage image={img} x={u.x * k + view.x} y={-u.y * k + view.y} width={u.width * k} height={underlayHeight(u) * k} rotation={-u.rotation_deg} opacity={u.opacity} listening={false} />
}

/** Scanned plans drawn under the grid's drawing (screen space, so the image stays crisp at any zoom). */
export default function UnderlayLayer({ underlays, pid, levelId, view }) {
  const list = (underlays || []).filter((u) => u.visible && (u.level_id == null || u.level_id === levelId))
  if (!list.length) return null
  return <Layer listening={false}>{list.map((u) => <One key={u.id} u={u} pid={pid} view={view} />)}</Layer>
}
