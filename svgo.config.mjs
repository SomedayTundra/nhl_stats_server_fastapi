// Conservative SVGO pass for the team logos in app/logos/.
// These files carry only a viewBox (no width/height) and are consumed both as <img>/<image>
// sources and as the input to scripts/build-logos.mjs. SVGO v4's preset-default keeps the
// viewBox on its own; we only relax id cleanup in case anything references a fragment.
export default {
    multipass: true,
    plugins: [
        {
            name: 'preset-default',
            params: {
                overrides: {
                    cleanupIds: false,
                },
            },
        },
    ],
}
