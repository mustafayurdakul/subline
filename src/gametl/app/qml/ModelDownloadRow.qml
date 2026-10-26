import QtQuick
import "Icons.js" as Icons

// The offline model for the language pair: one download, with its progress as the helper.
SettingRow {
    label: "Offline model"
    helper: backend.downloadStatus !== "" ? backend.downloadStatus : "For the language pair; about 100 MB, once."
    SecondaryButton { text: "Download"; icon_: Icons.download; enabled: !backend.downloading; onClicked: backend.downloadModel() }
}
