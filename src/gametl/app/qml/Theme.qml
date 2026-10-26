pragma Singleton
import QtQuick

// The design tokens every component reads: one palette, one spacing grid,
// one type scale. Dark by default; a light palette can swap the colours.
QtObject {
    readonly property color window: "#0E1116"
    readonly property color sidebar: "#121620"
    readonly property color card: "#171C26"
    readonly property color cardRaised: "#1C2230"
    readonly property color border: "#252C3A"
    readonly property color borderStrong: "#333C4E"
    readonly property color field: "#0F131A"
    readonly property color text: "#E9ECF2"
    readonly property color textSoft: "#B6BDCB"
    readonly property color muted: "#8690A4"
    readonly property color accent: "#4C8DFF"
    readonly property color accentSoft: "#1D2C47"
    readonly property color textOnAccent: "#FFFFFF"
    readonly property color success: "#3DD68C"
    readonly property color warning: "#F2B84B"
    readonly property color danger: "#EF6470"

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
