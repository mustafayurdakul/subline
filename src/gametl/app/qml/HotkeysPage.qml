import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

ColumnLayout {
    id: root
    readonly property var s: backend.settings
    spacing: 2 * Theme.space

    Card {
        title: "Shortcuts"
        helper: "They work in the game too. Click a field and press the keys; Esc leaves it, Backspace restores the default."
        Repeater {
            model: ["toggle", "pause", "rescan", "select", "settings"]
            SettingRow {
                id: row
                required property string modelData
                label: backend.hotkeyLabels[modelData]
                HotkeyField { map: root.s; key: "hotkey_" + row.modelData; fallback: backend.defaultHotkeys[row.modelData] }
            }
        }
        RowLayout {
            Layout.topMargin: Theme.space
            SecondaryButton { text: "Reset all to defaults"; icon_: Icons.refresh; onClicked: backend.resetHotkeys() }
        }
    }
}
