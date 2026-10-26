import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

ColumnLayout {
    spacing: 2 * Theme.space

    Card {
        title: "Shortcuts"
        helper: "They work in the game too. Click a field and press the keys; Esc leaves it, Backspace restores the default."
        Repeater {
            model: backend.hotkeyNames
            SettingRow {
                id: row
                required property string modelData
                label: backend.hotkeyLabels[modelData]
                HotkeyField { key: "hotkey_" + row.modelData; fallback: backend.defaultHotkeys[row.modelData] }
            }
        }
        SecondaryButton { Layout.topMargin: Theme.space; text: "Reset all to defaults"; icon_: Icons.refresh; onClicked: backend.resetHotkeys() }
    }
}
