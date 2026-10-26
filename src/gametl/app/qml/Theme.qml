pragma Singleton
import QtQuick

// The design tokens every component reads: one palette, one spacing grid,
// one type scale. Neutral zinc greys on near-black; no hue anywhere in the
// chrome, so the game's own colours in the preview are the only colour.
QtObject {
    readonly property color window: "#09090B"
    readonly property color sidebar: "#0C0C0E"
    readonly property color card: "#131316"
    readonly property color cardRaised: "#1C1C21"
    readonly property color border: "#27272A"
    readonly property color borderStrong: "#3F3F46"
    readonly property color field: "#0F0F12"
    readonly property color text: "#FAFAFA"
    readonly property color textSoft: "#D4D4D8"
    readonly property color muted: "#8E8E97"
    readonly property color primary: "#E4E4E7"      // filled buttons, switches that are on
    readonly property color textOnPrimary: "#09090B"
    readonly property color selection: "#52525B"
    readonly property color danger: "#E5484D"       // destructive actions only

    readonly property int space: 8
    readonly property int radius: 12
    readonly property int radiusSmall: 8
    readonly property int sidebarWidth: 224
    readonly property int contentWidth: 680

    readonly property string font: "Inter"  // Segoe UI Variable on Windows; Inter is the bundled fallback
    readonly property int size: 14
    readonly property int sizeSmall: 12
    readonly property int sizeTitle: 15
    readonly property int sizeHeading: 22
}
