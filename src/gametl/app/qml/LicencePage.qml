import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

ColumnLayout {
    id: root
    spacing: 2 * Theme.space

    Card {
        title: "Licence"
        helper: "Without a key the app runs for a " + backend.trialDays + "-day trial. The key is kept in Windows Credential Manager, never in a profile."
        SettingRow {
            label: "Status"
            Text { text: backend.licenseText; color: Theme.textSoft; font.family: Theme.font; font.pixelSize: Theme.size; wrapMode: Text.WordWrap; width: 360; horizontalAlignment: Text.AlignRight }
        }
        SettingRow {
            label: "Licence key"
            RowLayout {
                spacing: Theme.space
                Field { id: keyField; placeholderText: "GAMETL-..."; implicitWidth: 260; onAccepted: activate.clicked() }
                SecondaryButton { id: activate; text: "Activate"; icon_: Icons.check; onClicked: { backend.activateLicense(keyField.text); keyField.text = "" } }
                SecondaryButton { text: "Remove"; onClicked: backend.removeLicense() }
            }
        }
        RowLayout {
            visible: backend.purchaseUrl !== ""
            SecondaryButton { text: "Buy a licence"; icon_: Icons.external; onClicked: Qt.openUrlExternally(backend.purchaseUrl) }
        }
    }

    Card {
        title: "Data on this computer"
        helper: backend.dataDescription
        RowLayout {
            spacing: Theme.space
            SecondaryButton { text: "Open data folder"; icon_: Icons.folder; onClicked: backend.openDataFolder() }
            Item { Layout.fillWidth: true }
            SecondaryButton { text: "Remove all data and quit"; icon_: Icons.trash; danger: true; onClicked: confirm.open() }
        }
        Text {
            Layout.fillWidth: true
            text: "Removing deletes the folder and the Credential Manager entries above: profiles, translation caches, downloaded models, API keys, licence key and trial start. Then the app quits. Nothing of it stays apart from the program folder."
            color: Theme.muted; font.family: Theme.font; font.pixelSize: Theme.sizeSmall; wrapMode: Text.WordWrap
        }
    }

    Confirm {
        id: confirm
        title: "Remove all data and quit?"
        text: "Every profile, translation cache, downloaded model, the API keys, the licence key and the trial record go. This cannot be undone."
        confirmText: "Remove and quit"
        onConfirmed: backend.removeAllData()
    }
}
