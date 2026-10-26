import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

ColumnLayout {
    id: root
    property var backend
    spacing: 2 * Theme.space

    Card {
        title: "Game"
        SettingRow {
            label: "Game window"
            helper: "Part of the window title is enough."
            RowLayout {
                spacing: Theme.space
                Field { text: backend.windowMatch; implicitWidth: 260 }
                SecondaryButton { text: "Refresh"; icon_: Icons.refresh }
            }
        }
        SettingRow {
            label: "Game name"
            helper: "Used in the prompt and for the translation cache."
            Field { text: backend.game; implicitWidth: 260 }
        }
    }

    Card {
        title: "Area to translate"
        helper: "Only this part of the window is read. Saved as fractions, so it survives resizes."
        SettingRow {
            label: "Area"
            helper: "x, y, width, height as fractions of the window"
            Field { text: backend.roi; implicitWidth: 220 }
        }
        RowLayout {
            spacing: Theme.space
            SecondaryButton { text: "Bottom strip" }
            SecondaryButton { text: "Select on screen"; icon_: Icons.crosshair }
            SecondaryButton { text: "Whole window" }
        }
        SettingRow {
            label: "Keep a selected area centred"
            helper: "Shift while dragging inverts this for one drag."
            Toggle { checked: backend.centerZone }
        }
    }

    Card {
        title: "Ignore"
        helper: "What never gets translated, even inside the area."
        SettingRow {
            label: "Patterns"
            helper: "Regular expressions, one per line, case-insensitive."
            Field { text: "^[\\W\\d_]*$"; implicitWidth: 260 }
        }
        SettingRow {
            label: "Zones"
            helper: "Rectangles to leave alone, such as a minimap."
            Field { placeholderText: "x,y,w,h per line"; implicitWidth: 260 }
        }
        SettingRow {
            label: "Short lines need OCR confidence"
            helper: "One- or two-letter lines are kept only when OCR is this sure of them."
            Gauge { value: 90; from: 0; to: 100; suffix: " %"; specialText: "off" }
        }
    }

    Card {
        title: "Window"
        SettingRow { label: "Read the title bar and frame too"; Toggle { checked: false } }
        SettingRow { label: "Hide the overlay when the game is not in front"; Toggle { checked: true } }
        SettingRow {
            label: "Keep the overlay out of recordings"
            helper: "Streams and screenshots will not show translations."
            Toggle { checked: false }
        }
    }
}
