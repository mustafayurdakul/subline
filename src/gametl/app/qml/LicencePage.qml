import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

ColumnLayout {
    spacing: 2 * Theme.space

    Card {
        title: "Licence"
        helper: "Without a key the app translates for " + backend.trialHours + " hours in all, then stops. A key is issued for one computer, named by the code below, and is kept in Windows Credential Manager, never in a profile."
        SettingRow {
            label: "Status"
            Label { text: backend.licenseText; color: Theme.textSoft; wrapMode: Text.WordWrap; width: 360; horizontalAlignment: Text.AlignRight }
        }
        SettingRow {
            label: "Computer code"
            helper: "Send this code when buying a key; the key works on this computer only."
            RowLayout {
                spacing: Theme.space
                Label { text: backend.machineCode; font.family: "Consolas"; font.pixelSize: Theme.size; color: Theme.textSoft }
                SecondaryButton { text: "Copy"; onClicked: backend.copyMachineCode() }
            }
        }
        SettingRow {
            label: "Licence key"
            RowLayout {
                spacing: Theme.space
                Field { id: keyField; placeholderText: "GAMETL-..."; onAccepted: activate.clicked() }
                SecondaryButton { id: activate; text: "Activate"; icon_: Icons.check; onClicked: { backend.activateLicense(keyField.text); keyField.text = "" } }
                SecondaryButton { text: "Remove"; onClicked: confirmRemoveKey.open() }
            }
        }
        SecondaryButton { visible: backend.purchaseUrl !== ""; text: "Buy a licence"; icon_: Icons.external; onClicked: Qt.openUrlExternally(backend.purchaseUrl) }
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
        Caption {
            Layout.fillWidth: true
            text: "Removing deletes the folder and the Credential Manager entries above: profiles, translation caches, downloaded models, API keys and the licence key. Then the app quits. Only the trial's used time (gametl/TRIAL_USED) is kept, so the trial does not start over."
        }
    }

    Confirm {
        id: confirm
        title: "Remove all data and quit?"
        text: "Every profile, translation cache, downloaded model, the API keys and the licence key go; only the trial's used time stays. This cannot be undone."
        confirmText: "Remove and quit"
        onConfirmed: backend.removeAllData()
    }

    Confirm {
        id: confirmRemoveKey
        title: "Remove the licence key?"
        text: "The key is removed from this computer. Without it the app runs on what is left of the trial; the key can be entered again later."
        confirmText: "Remove key"
        onConfirmed: backend.removeLicense()
    }
}
