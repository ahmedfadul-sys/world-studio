// Material Lab presets: values mirror blender_scripts/matlab.py and backend MaterialLab.
export const LAB_PRESETS = ['brick', 'concrete', 'plaster', 'wood', 'tile', 'marble', 'stone', 'metal', 'asphalt']

const base = { scale: 4, roughness: 0.8, metallic: 0, bump: 1, variation: 0.5, seed: 1, resolution: 1024, tile_m: 1 }
export const LAB_DEFAULTS = {
  brick: { ...base, color1: '#a4533a', color2: '#8a4330', joint: '#b7b0a4', scale: 5, roughness: 0.85, tile_m: 1 },
  concrete: { ...base, color1: '#9a9a96', color2: '#7d7d79', joint: '#000000', roughness: 0.85, bump: 0.8, variation: 0.6, tile_m: 2 },
  plaster: { ...base, color1: '#e8dfd0', color2: '#d6c9b4', joint: '#000000', roughness: 0.9, bump: 0.5, tile_m: 2 },
  wood: { ...base, color1: '#b9814d', color2: '#7a4a24', joint: '#2a1a0e', scale: 4, roughness: 0.5, bump: 0.6, tile_m: 1.2 },
  tile: { ...base, color1: '#e9e6df', color2: '#dcd8cf', joint: '#8f8b84', scale: 4, roughness: 0.25, bump: 0.5, variation: 0.4, tile_m: 1.6 },
  marble: { ...base, color1: '#f1f0ee', color2: '#cfcfd3', joint: '#5b5e66', roughness: 0.15, bump: 0.1, variation: 0.6, tile_m: 2 },
  stone: { ...base, color1: '#8c8579', color2: '#6e675c', joint: '#4a463f', scale: 3, roughness: 0.9, bump: 1.2, variation: 0.6, tile_m: 1.5 },
  metal: { ...base, color1: '#b9bcc1', color2: '#8e9298', joint: '#000000', roughness: 0.35, metallic: 1, bump: 0.2, tile_m: 1 },
  asphalt: { ...base, color1: '#3b3b3d', color2: '#2a2a2c', joint: '#000000', roughness: 0.92, bump: 1, tile_m: 1.5 },
}

// which controls matter for which preset (the rest are hidden)
export const LAB_USES = {
  brick: { joint: 'lab_j_mortar', scale: 'lab_s_bricks' }, tile: { joint: 'lab_j_grout', scale: 'lab_s_tiles', even: true },
  wood: { joint: 'lab_j_gap', scale: 'lab_s_planks' }, stone: { joint: 'lab_j_mortar', scale: 'lab_s_stones' },
  marble: { joint: 'lab_j_veins' }, concrete: {}, plaster: {}, metal: {}, asphalt: {},
}

/** Parameters after switching preset: keep the user's resolution, otherwise take the preset's own values. */
export const presetParams = (preset, keep = {}) => ({ preset, ...LAB_DEFAULTS[preset], resolution: keep.resolution || LAB_DEFAULTS[preset].resolution })
