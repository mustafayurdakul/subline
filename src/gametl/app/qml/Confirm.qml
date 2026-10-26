import QtQuick
import QtQuick.Layouts

// A question with one dangerous answer.
Dialog {
    id: root
    property string text: ""
    property string confirmText: "Remove"
    signal confirmed()

    Label { text: root.text; color: Theme.textSoft; wrapMode: Text.WordWrap; Layout.fillWidth: true }
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.space
        Item { Layout.fillWidth: true }
        SecondaryButton { text: "Cancel"; onClicked: root.close() }
        SecondaryButton { text: root.confirmText; danger: true; onClicked: { root.close(); root.confirmed() } }
    }
}
