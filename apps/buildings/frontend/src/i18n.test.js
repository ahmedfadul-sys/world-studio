import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { DICT } from './i18n.js'

const walk = (d) => readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : [join(d, f)]))
const files = walk(new URL('.', import.meta.url).pathname).filter((f) => /\.jsx$/.test(f))
const src = files.map((f) => readFileSync(f, 'utf8')).join('\n')

describe('i18n', () => {
  const used = new Set()
  for (const m of src.matchAll(/\bt\(\s*'([a-z0-9_]+)'\s*\)/g)) used.add(m[1])
  for (const m of src.matchAll(/'((?:nav|tool|v)_[a-z]+)'/g)) used.add(m[1])
  for (const m of src.matchAll(/label: '([a-z]_[a-z_]+|f_[a-z_]+)'/g)) used.add(m[1])
  it('has every static key in both languages', () => {
    const missing = [...used].filter((k) => !(k in DICT.en) || !(k in DICT.ar))
    expect(missing).toEqual([])
  })
  it('dynamic key families exist', () => {
    for (const k of ['wall', 'door', 'window', 'column', 'beam', 'floor', 'roof', 'stair', 'room', 'select', 'move', 'delete', 'hand', 'opening', 'decor']) expect(DICT.ar['tool_' + k]).toBeTruthy()
    for (const k of ['dashboard', 'projects', 'editor', 'preview', 'building', 'materials', 'modules', 'optimize', 'collision', 'lod', 'uv', 'export', 'settings', 'perf']) expect(DICT.ar['nav_' + k]).toBeTruthy()
    for (const k of ['box', 'round', 'flat', 'shed', 'gable', 'hip', 'floor', 'ceiling', 'balcony', 'rect', 'arch']) expect(DICT.ar['v_' + k]).toBeTruthy()
  })
  it('Arabic and English define the same keys', () => {
    expect(Object.keys(DICT.ar).sort()).toEqual(Object.keys(DICT.en).sort())
  })
})
