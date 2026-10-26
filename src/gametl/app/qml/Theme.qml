pragma Singleton
import QtQuick

// The design tokens every component reads: one palette, one spacing grid,
// one type scale. Sharp corners; zinc greys on near-black with one muted
// accent (a dim gold) for the things that matter: the filled button, a
// switch that is on, the active page, focus.
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
    readonly property color accent: "#A98E5C"       // dim gold: filled button, switch on, active page, focus
    readonly property color accentSoft: "#26221A"   // the accent at 15 %, for the active page's row
    readonly property color accentDeep: "#6E5C3C"   // outlines in the accent that must stay quiet
    readonly property color textOnAccent: "#0B0A08"
    readonly property color selection: "#4A4234"
    readonly property color danger: "#B5484D"       // destructive actions only

    readonly property int space: 8
    readonly property int radius: 0
    readonly property int radiusSmall: 0
    readonly property int sidebarWidth: 224
    readonly property int contentWidth: 680

    readonly property string font: Qt.platform.os === "windows" ? "Segoe UI" : "Inter"
    readonly property int size: 14
    readonly property int sizeSmall: 12
    readonly property int sizeTitle: 15
    readonly property int sizeHeading: 22
}
