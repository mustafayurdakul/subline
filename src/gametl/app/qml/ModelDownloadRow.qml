import QtQuick
import "Icons.js" as Icons

// The offline translator: its runtime (once) and the model for the language
// pair, one download, with its progress as the helper.
SettingRow {
    label: "Offline translation"
    helper: backend.downloadStatus !== "" ? backend.downloadStatus : "Not in the app itself: about 120 MB, once per language pair."
    SecondaryButton { text: "Download"; icon_: Icons.download; enabled: !backend.downloading; onClicked: backend.downloadOffline() }
}
