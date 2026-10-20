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

// every crest shares a 960x640 viewBox, but how much of that canvas the artist actually drew
// into varies a lot per logo (measured fill ratios across the set range from ~52% to 100%).
// Naively "contain"-fitting the raw viewBox means loosely-drawn crests render visibly smaller
// than tightly-drawn ones at the same on-screen size (e.g. STL's 2008-09-2024-25 crest has far
// less internal padding than most, so it looked oversized next to every other team's hover
// logo on the chart). So we trim to the actual ink first.
//
// Fitting that trimmed box's *longest side* to a fixed fraction still isn't enough, though: it
// equalizes width, not visual weight. A square, solid crest (HFD's 1979-92 whale, which fills
// its box corner to corner) came out several times heavier than a wide wordmark like WSH's
// 1974-95 one, which got pinned by its width and left short and thin. Instead each logo is
// scaled so its "effective size" hits one target:
//
//     effective size = sqrt(w * h) * density^DENSITY_WEIGHT,   density = ink / (w * h)
//
// DENSITY_WEIGHT = 0 would equalize bounding-box area; 0.5 would equalize raw ink area, which
// overcorrects (every crest identical in ink, thin wordmarks blown up). 0.3 sits between.
// Ink is alpha coverage, not "non-white", so the result doesn't depend on the page theme.
const DENSITY_WEIGHT = 0.3
// effective size as a fraction of the canvas edge; 0.575 was the set's median under the old
// longest-side-at-72% fit, so a typical logo stays put and only the outliers move
const TARGET_SIZE = 0.575
// no logo's longest side may exceed this fraction of the canvas, so wide wordmarks that the
// area target wants to grow still keep some breathing room at the edges
const MAX_FILL = 0.9
// alpha below this (out of 255) doesn't count toward a logo's ink
const MIN_INK_ALPHA = 16

// a trimmed raster's dimensions and effective size (see above), both in its own pixels
async function measureLogo(trimmedBuffer) {
    const {data, info} = await sharp(trimmedBuffer).ensureAlpha().raw().toBuffer({resolveWithObject: true})
    const {width: w, height: h, channels} = info
    let ink = 0
    for (let i = channels - 1; i < data.length; i += channels) {
        if (data[i] >= MIN_INK_ALPHA) ink += data[i] / 255
    }
    const density = ink / (w * h)
    return {w, h, effectiveSize: Math.sqrt(w * h) * Math.pow(density, DENSITY_WEIGHT)}
}

// the content size that brings a measured logo to TARGET_SIZE of a `px`-edged canvas
function normalizedSize({w, h, effectiveSize}, px) {
    const scale = Math.min((px * TARGET_SIZE) / effectiveSize, (px * MAX_FILL) / Math.max(w, h))
    return {width: Math.max(1, Math.round(w * scale)), height: Math.max(1, Math.round(h * scale))}
}

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

    const trimmedBuffer = await sharp(svgBuffer, {density: RENDER_DENSITY})
        .trim({background: {r: 0, g: 0, b: 0, alpha: 0}})
        .toBuffer()
    const measured = await measureLogo(trimmedBuffer)

    for (const [label, px] of Object.entries(SIZES)) {
        const {width, height} = normalizedSize(measured, px)
        const content = await sharp(trimmedBuffer)
            .resize(width, height, {fit: 'fill'})
            .toBuffer()

        await sharp({create: {width: px, height: px, channels: 4, background: {r: 0, g: 0, b: 0, alpha: 0}}})
            .composite([{input: content, gravity: 'center'}])
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
