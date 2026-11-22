import type { Preview } from "./types";

type RGB = [number, number, number];
const LAND: [number, RGB][] = [[0, [92, 138, 84]], [0.3, [170, 160, 98]], [0.6, [128, 104, 84]], [1, [244, 244, 240]]];
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

function landColor(t: number): RGB {
  for (let i = 1; i < LAND.length; i++) {
    if (t <= LAND[i][0]) {
      const [t0, c0] = LAND[i - 1], [t1, c1] = LAND[i], k = (t - t0) / (t1 - t0);
      return [lerp(c0[0], c1[0], k), lerp(c0[1], c1[1], k), lerp(c0[2], c1[2], k)];
    }
  }
  return LAND[LAND.length - 1][1];
}

export const zAt = (pv: Preview, i: number) => pv.zmin + (pv.u16[i] / 65535) * (pv.zmax - pv.zmin);

/** نموذج الارتفاع من المعاينة عند إحداثي عالمي (أقرب بكسل). */
export function sampleZ(pv: Preview, x: number, y: number, Lx: number, Ly: number): number {
  const c = Math.min(pv.nx - 1, Math.max(0, Math.round((x / Lx) * (pv.nx - 1))));
  const r = Math.min(pv.ny - 1, Math.max(0, Math.round(((Ly - y) / Ly) * (pv.ny - 1))));
  return zAt(pv, r * pv.nx + c);
}

/** ألوان ارتفاعية (ماء تحت مستوى البحر) + Hillshade من الشمال الغربي. */
export function renderTerrain(pv: Preview, sea: number, Lx: number, Ly: number, ex = 3, useColors = false): ImageData {
  const { nx, ny } = pv, mx = Lx / (nx - 1), my = Ly / (ny - 1), img = new ImageData(nx, ny), L = [-0.5, 0.5, Math.SQRT1_2];
  for (let r = 0; r < ny; r++) {
    for (let c = 0; c < nx; c++) {
      const i = r * nx + c, h = zAt(pv, i);
      const cl = Math.max(c - 1, 0), cr = Math.min(c + 1, nx - 1), ru = Math.max(r - 1, 0), rd = Math.min(r + 1, ny - 1);
      const dzdx = (zAt(pv, r * nx + cr) - zAt(pv, r * nx + cl)) / ((cr - cl) * mx);
      const dzdn = -(zAt(pv, rd * nx + c) - zAt(pv, ru * nx + c)) / ((rd - ru) * my);
      const gx = -dzdx * ex, gy = -dzdn * ex, shade = Math.max(0, (gx * L[0] + gy * L[1] + L[2]) / Math.hypot(gx, gy, 1));
      let col: RGB;
      if (useColors && pv.color) col = [pv.color[i * 3], pv.color[i * 3 + 1], pv.color[i * 3 + 2]];
      else if (h < sea) {
        const d = Math.min(1, (sea - h) / Math.max(1, sea - pv.zmin));
        col = [lerp(48, 14, d), lerp(104, 44, d), lerp(168, 98, d)];
      } else col = landColor(Math.min(1, (h - sea) / Math.max(1e-6, pv.zmax - sea)));
      const f = 0.35 + 0.9 * shade, o = i * 4;
      img.data[o] = Math.min(255, col[0] * f); img.data[o + 1] = Math.min(255, col[1] * f);
      img.data[o + 2] = Math.min(255, col[2] * f); img.data[o + 3] = 255;
    }
  }
  return img;
}
