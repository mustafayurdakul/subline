import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

ColumnLayout {
    id: root
    readonly property var s: backend.settings
    spacing: 2 * Theme.space

    Card {
        title: "Capture"
        SettingRow {
            label: "Capture rate"
            helper: "Frames read per second. Subtitles need no more than ten."
            Gauge { map: root.s; key: "fps"; from: 1; to: 60; suffix: " fps" }
        }
        SettingRow {
            label: "Skip unchanged frames below"
            helper: "OCR waits while the area looks the same as last time. Lower it if a change is ever missed."
            Gauge { map: root.s; key: "diff_threshold"; from: 0; to: 50; stepSize: 0.5; decimals: 1; specialText: "off" }
        }
        SettingRow {
            label: "Stable frames"
            helper: "How many frames a line must hold still before it is translated."
            Stepper { map: root.s; key: "stable_frames"; from: 1; to: 10 }
        }
        SettingRow {
            label: "Keep a line for"
            helper: "Frames a line may go unread before its translation is taken down."
            Stepper { map: root.s; key: "max_missing"; from: 0; to: 30; suffix: " frames" }
        }
        SettingRow {
            label: "Sweep the whole area every"
            helper: "With a zone set, also read the rest of the area now and then."
            Stepper { map: root.s; key: "full_scan_every"; from: 0; to: 600; step: 10; suffix: " frames"; specialText: "never" }
        }
    }

    Card {
        title: "Translation"
        SettingRow {
            label: "Write the cache every"
            Stepper { map: root.s; key: "autosave_seconds"; from: 0; to: 120; step: 5; suffix: " s"; specialText: "at exit" }
        }
        SettingRow {
            label: "Translator by name"
            helper: "Any of claude, deepl, offline; or uppercase, echo and verbose for testing without a key."
            Field { map: root.s; key: "translator"; implicitWidth: 180 }
        }
    }

    Card {
        title: "Diagnostics"
        helper: "The log file is gametl.log in the data folder."
        RowLayout {
            spacing: Theme.space
            Text { text: backend.dataFolder; color: Theme.textSoft; font.family: Theme.font; font.pixelSize: Theme.sizeSmall + 1; elide: Text.ElideMiddle; Layout.fillWidth: true }
            SecondaryButton { text: "Open data folder"; icon_: Icons.folder; onClicked: backend.openDataFolder() }
        }
    }
}
