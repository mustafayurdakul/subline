import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A modal question with one dangerous answer.
Popup {
    id: root
    property string title: ""
    property string text: ""
    property string confirmText: "Remove"
    signal confirmed()

    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape
    anchors.centerIn: Overlay.overlay
    width: 460
    padding: 3 * Theme.space
    background: Rectangle { color: Theme.card; border.color: Theme.borderStrong }
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.6) }

    contentItem: ColumnLayout {
        spacing: 2 * Theme.space
        Text { text: root.title; color: Theme.text; font.family: Theme.font; font.pixelSize: Theme.sizeTitle; font.weight: Font.DemiBold }
        Text { text: root.text; color: Theme.textSoft; font.family: Theme.font; font.pixelSize: Theme.size; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space
            Item { Layout.fillWidth: true }
            SecondaryButton { text: "Cancel"; onClicked: root.close() }
            SecondaryButton { text: root.confirmText; danger: true; onClicked: { root.close(); root.confirmed() } }
        }
    }
}
