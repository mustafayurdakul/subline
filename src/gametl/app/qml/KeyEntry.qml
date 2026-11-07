import QtQuick
import QtQuick.Layouts

// An API key: paste, Save (also Enter), and the field is blanked once the
// key is in the credential store. Clear removes a stored key; `clearable:
// false` leaves that button out where no key is stored yet (Home).
RowLayout {
    id: root
    property string name: ""  // the secret's name, as the backend knows it
    property bool clearable: true
    spacing: Theme.space
    Field { id: field; placeholderText: "paste the key"; secret: true; implicitWidth: 240; onAccepted: save.clicked() }
    SecondaryButton { id: save; text: "Save"; onClicked: if (backend.saveKey(root.name, field.text)) field.text = "" }
    SecondaryButton { visible: root.clearable; text: "Clear"; onClicked: { backend.clearKey(root.name); field.text = "" } }
}
