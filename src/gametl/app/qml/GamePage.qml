import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

ColumnLayout {
    id: root
    readonly property var s: backend.settings
    spacing: 2 * Theme.space

    Component.onCompleted: backend.refreshWindows()

    Card {
        title: "Game"
        SettingRow {
            label: "Game window"
            helper: "Part of the window title is enough."
            RowLayout {
                spacing: Theme.space
                Combo { map: root.s; key: "window_match"; options: backend.windows; implicitWidth: 260 }
                SecondaryButton { text: "Refresh"; icon_: Icons.refresh; onClicked: backend.refreshWindows() }
            }
        }
        SettingRow {
            label: "Game name"
            helper: "Used in the prompt and for the translation cache."
            Field { map: root.s; key: "game"; placeholderText: "default: the window title"; implicitWidth: 260 }
        }
    }

    Card {
        title: "Area to translate"
        helper: "Only this part of the window is read. Saved as fractions, so it survives resizes."
        SettingRow {
            label: "Area"
            helper: "x, y, width, height as fractions of the window"
            Field { map: root.s; key: "roi"; placeholderText: "empty: the whole window"; implicitWidth: 220 }
        }
        RowLayout {
            spacing: Theme.space
            SecondaryButton { text: "Bottom strip"; onClicked: backend.useBottomStrip() }
            SecondaryButton { text: "Select on screen"; icon_: Icons.crosshair; onClicked: backend.selectArea() }
            SecondaryButton { text: "Whole window"; onClicked: backend.useWholeWindow() }
        }
        SettingRow {
            label: "Keep a selected area centred"
            helper: "Shift while dragging inverts this for one drag."
            Toggle { map: root.s; key: "center_zone" }
        }
    }

    Card {
        title: "Ignore"
        helper: "What never gets translated, even inside the area."
        SettingRow {
            label: "Patterns"
            helper: "Regular expressions, one per line, case-insensitive."
            MultiField { map: root.s; key: "ignore_patterns"; placeholderText: "one per line" }
        }
        SettingRow {
            label: "Zones"
            helper: "Rectangles to leave alone, such as a minimap."
            MultiField { map: root.s; key: "ignore_zones"; placeholderText: "x,y,w,h per line" }
        }
        SettingRow {
            label: "Short lines need OCR confidence"
            helper: "One- or two-letter lines are kept only when OCR is this sure of them."
            Gauge { map: root.s; key: "short_line_confidence"; scale: 100; from: 0; to: 100; stepSize: 5; suffix: " %"; specialText: "off" }
        }
    }

    Card {
        title: "Window"
        SettingRow { label: "Read the title bar and frame too"; Toggle { map: root.s; key: "include_frame" } }
        SettingRow { label: "Hide the overlay when the game is not in front"; Toggle { map: root.s; key: "hide_when_unfocused" } }
        SettingRow {
            label: "Keep the overlay out of recordings"
            helper: "Streams and screenshots will not show translations."
            Toggle { map: root.s; key: "exclude_from_capture" }
        }
    }
}
