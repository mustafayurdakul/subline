import QtQuick
import QtQuick.Layouts

ColumnLayout {
    spacing: 2 * Theme.space

    Card {
        title: "Game"
        SettingRow { label: "Game window"; helper: "Part of the window title is enough."; WindowPicker {} }
        SettingRow {
            label: "Game name"
            helper: "Names the translation cache (and, with Claude, the game in the prompt). Empty: the Game window text above."
            Field { key: "game"; live: false; placeholderText: "default: the Game window text" }
        }
    }

    Card {
        title: "Area to translate"
        helper: "Only this part of the window is read. Saved as fractions, so it survives resizes."
        SettingRow {
            label: "Area"
            helper: "x, y, width, height as fractions of the window."
            Field { key: "roi"; placeholderText: "empty: the whole window"; implicitWidth: 220 }
        }
        AreaButtons { Layout.alignment: Qt.AlignRight }
        SettingRow {
            label: "Keep a selected area centred"
            helper: "Shift while dragging inverts this for one drag."
            Toggle { key: "center_area" }
        }
    }

    Card {
        title: "Ignore"
        helper: "What never gets translated, even inside the area."
        SettingRow {
            label: "Patterns"
            helper: "Regular expressions, one per line, case-insensitive."
            MultiField { key: "ignore_patterns"; placeholderText: "one per line" }
        }
        SettingRow {
            label: "Zones"
            helper: "Rectangles to leave alone, such as a minimap."
            MultiField { key: "ignore_zones"; placeholderText: "x,y,w,h per line" }
        }
        SettingRow {
            label: "Short lines need OCR confidence"
            helper: "One- or two-letter lines are kept only when OCR is this sure of them."
            Gauge { key: "short_line_confidence"; factor: 100; from: 0; to: 100; stepSize: 5; suffix: "%"; specialText: "off" }
        }
    }

    Card {
        title: "Window"
        SettingRow { label: "Read the title bar and frame too"; Toggle { key: "include_frame" } }
        SettingRow { label: "Hide the overlay when the game is not in front"; Toggle { key: "hide_when_unfocused" } }
        SettingRow {
            label: "Keep the overlay out of recordings"
            helper: "Streams and screenshots will not show translations."
            Toggle { key: "exclude_from_capture" }
        }
    }
}
