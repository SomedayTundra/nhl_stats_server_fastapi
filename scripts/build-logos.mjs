// Optimize the team logo SVGs in app/logos/ in place, then pre-rasterize each one to
// square PNGs at the sizes the client actually displays. The browser was downscaling the
// 960x640 vector artwork to ~48px in a single pass, which left the detailed historical
// crests looking scratchy; sharp's lanczos3 downsample from a high-resolution render is
// much cleaner. The /logo route serves these when the client asks for ?size=1x|2x and
// falls back to the SVG when a PNG is missing.
//
// Run: npm run build:logos   (re-run whenever the SVGs in app/logos/ change)

import {readdir, readFile, writeFile} from 'node:fs/promises'
import {basename, extname, join} from 'node:path'
import {fileURLToPath} from 'node:url'

import sharp from 'sharp'
import {optimize} from 'svgo'

import svgoConfig from '../svgo.config.mjs'

const LOGOS_DIR = fileURLToPath(new URL('../app/logos', import.meta.url))

// keys match the ?size= values the /logo route accepts; px is the square PNG edge.
// 2x (128) covers the largest on-screen logo (64px chart logo on a 2x display).
const SIZES = {'1x': 64, '2x': 128}

// render the SVG well above the target size so the lanczos3 downsample has detail to work
// with (viewBox is 960 wide, so this is ~2x supersampling before the resize).
const RENDER_DENSITY = 144

const svgFiles = (await readdir(LOGOS_DIR))
    .filter((name) => extname(name).toLowerCase() === '.svg')
    .sort()

if (svgFiles.length === 0) {
    console.error(`no .svg files found in ${LOGOS_DIR}`)
    process.exit(1)
}

let optimizedCount = 0
let bytesSaved = 0
let pngCount = 0

for (const name of svgFiles) {
    const svgPath = join(LOGOS_DIR, name)
    const originalSvg = await readFile(svgPath, 'utf8')

    const {data: optimizedSvg} = optimize(originalSvg, {...svgoConfig, path: svgPath})
    if (optimizedSvg.length < originalSvg.length) {
        await writeFile(svgPath, optimizedSvg)
        bytesSaved += Buffer.byteLength(originalSvg) - Buffer.byteLength(optimizedSvg)
        optimizedCount++
    }

    const stem = basename(name, extname(name))
    const svgBuffer = Buffer.from(optimizedSvg)

    for (const [label, px] of Object.entries(SIZES)) {
        await sharp(svgBuffer, {density: RENDER_DENSITY})
            .resize(px, px, {fit: 'contain', background: {r: 0, g: 0, b: 0, alpha: 0}})
            .png({compressionLevel: 9, palette: true, quality: 90, effort: 10})
            .toFile(join(LOGOS_DIR, `${stem}@${label}.png`))
        pngCount++
    }

    console.log(`  ${name} -> ${stem}@1x.png, ${stem}@2x.png`)
}

console.log(
    `\n${svgFiles.length} SVG processed, ${optimizedCount} shrunk ` +
        `(${(bytesSaved / 1024).toFixed(1)} KiB saved), ${pngCount} PNG written`,
)
