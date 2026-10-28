import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

ColumnLayout {
    spacing: 2 * Theme.space

    Card {
        title: "Capture"
        SettingRow {
            label: "Capture rate"
            helper: "Frames read per second. Subtitles need no more than ten."
            Gauge { key: "fps"; from: 1; to: 60; suffix: " fps" }
        }
        SettingRow {
            label: "Change that wakes OCR"
            helper: "OCR waits while nothing in the area changes this much. Lower it if a line is ever missed."
            Gauge { key: "change_threshold"; from: 0; to: 100; stepSize: 5; specialText: "off" }
        }
        SettingRow {
            label: "Stable frames"
            helper: "How many frames a line must hold still before it is translated."
            Stepper { key: "stable_frames"; from: 1; to: 10 }
        }
        SettingRow {
            label: "Keep a line for"
            helper: "Frames a line may go unread before its translation is taken down."
            Stepper { key: "max_missing"; from: 0; to: 30; suffix: " frames" }
        }
        SettingRow {
            label: "Read the whole window every"
            helper: "With an area set, also read the rest of the window now and then."
            Stepper { key: "full_scan_every"; from: 0; to: 600; step: 10; suffix: " frames"; specialText: "never" }
        }
    }

    Card {
        title: "Translation"
        SettingRow {
            label: "Write the cache every"
            Stepper { key: "autosave_seconds"; from: 0; to: 120; step: 5; suffix: " s"; specialText: "at exit" }
        }
        SettingRow {
            label: "Translator by name"
            helper: "The three services, or uppercase, verbose and echo for testing without a key."
            Combo { key: "translator"; options: backend.translators; implicitWidth: 180 }
        }
    }

    Card {
        title: "Diagnostics"
        helper: "The log file is gametl.log in the data folder."
        RowLayout {
            spacing: Theme.space
            Label { text: backend.dataFolder; color: Theme.textSoft; font.pixelSize: Theme.sizeCaption; elide: Text.ElideMiddle; Layout.fillWidth: true }
            SecondaryButton { text: "Open data folder"; icon_: Icons.folder; onClicked: backend.openDataFolder() }
        }
    }
}
