// Text helpers shared by the pages.
.pragma library

// "ctrl+shift+t" -> "Ctrl + Shift + T".
function hotkey(combo) {
    return String(combo).split("+").map(function (part) {
        return part.length ? part.charAt(0).toUpperCase() + part.slice(1) : part
    }).join(" + ")
}
