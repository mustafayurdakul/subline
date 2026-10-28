pragma Singleton
import QtQuick

// The design tokens every component reads: one palette, one spacing grid,
// one type scale, one control height. A light, Windows 11 look: warm-grey
// window, white cards with soft corners, near-black text, and one accent
// (Windows blue) for the things that matter: the filled button, a switch
// that is on, the active page, focus.
//
// Sizes are at 96 dpi; the window scales the whole page to the screen
// (settings_window.py), so no token is multiplied here.
QtObject {
    readonly property color window: "#F3F3F3"
    readonly property color sidebar: "#F3F3F3"
    readonly property color card: "#FFFFFF"
    readonly property color cardRaised: "#F6F6F6"   // a control under the mouse
    readonly property color cardPressed: "#EBEBEB"  // a control held down
    readonly property color border: "#E5E5E5"       // card edges and dividers
    readonly property color borderStrong: "#C8C8C8" // the resting edge of every control
    readonly property color borderHover: "#9A9A9A"  // a control's edge under the mouse
    readonly property color field: "#FFFFFF"
    readonly property color text: "#1B1B1B"
    readonly property color textSoft: "#3A3A3A"
    readonly property color muted: "#6B6B6B"
    readonly property color accent: "#0067C0"       // filled button, switch on, active page, focus
    readonly property color accentSoft: "#E6F0FA"   // the accent at 10 %, for the active page's row and segment
    readonly property color textOnAccent: "#FFFFFF"
    readonly property color textOnDark: "#F2F2F2"   // on the always-dark subtitle preview
    readonly property color selection: "#CCE4F7"
    readonly property color danger: "#C42B1C"       // destructive actions only

    readonly property int space: 8
    readonly property int radius: 8
    readonly property int controlHeight: 32         // buttons, fields, drop-downs, steppers, segments
    readonly property real disabledOpacity: 0.45    // a control that cannot be used right now
    readonly property int sidebarWidth: 224
    readonly property int contentWidth: 680

    readonly property string font: Qt.platform.os === "windows" ? "Segoe UI" : "Inter"
    readonly property int size: 14         // labels, fields, buttons
    readonly property int sizeCaption: 13  // secondary text beside a control
    readonly property int sizeSmall: 12    // helper lines
    readonly property int sizeTiny: 11     // tags
    readonly property int sizeTitle: 15
    readonly property int sizeBrand: 16    // the app's name in the side navigation
    readonly property int sizeHeading: 22
    readonly property int sizeHero: 30     // the Home page's one sentence
}
