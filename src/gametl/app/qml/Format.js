// Text helpers shared by the pages.
.pragma library

// "ctrl+shift+t" -> "Ctrl + Shift + T" (or "Ctrl+Shift+T" with a "+" joiner).
function hotkey(combo, joiner) {
    return String(combo).split("+").map(function (part) {
        return part.length ? part.charAt(0).toUpperCase() + part.slice(1) : part
    }).join(joiner === undefined ? " + " : joiner)
}
