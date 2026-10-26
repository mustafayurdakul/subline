import QtQuick
import QtQuick.Layouts

// An API key: paste, Save (also Enter), and the field is blanked once the
// key is in the credential store. `clearable` adds a Clear button.
RowLayout {
    id: root
    property string name: ""  // the secret's name, as the backend knows it
    property bool clearable: false
    property int fieldWidth: 240
    spacing: Theme.space
    Field { id: field; placeholderText: "paste the key"; secret: true; implicitWidth: root.fieldWidth; onAccepted: save.clicked() }
    SecondaryButton { id: save; text: "Save"; onClicked: { backend.saveKey(root.name, field.text); field.text = "" } }
    SecondaryButton { visible: root.clearable; text: "Clear"; onClicked: { backend.clearKey(root.name); field.text = "" } }
}
