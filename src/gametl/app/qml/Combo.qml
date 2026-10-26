import QtQuick
import QtQuick.Controls.Basic
import "Icons.js" as Icons

// An editable drop-down: type a value or pick one of `options`. With `map`
// and `key` it follows and writes that settings entry.
ComboBox {
    id: root
    property var options: []
    property var map: null
    property string key: ""
    readonly property bool bound: map !== null && key !== ""

    editable: true
    model: options
    implicitWidth: 260
    implicitHeight: 34
    leftPadding: 12
    rightPadding: 36
    font.family: Theme.font
    font.pixelSize: Theme.size

    // The text comes from the map, not from editText: a model reset (the
    // window list refreshing) blanks editText, and must not blank the field.
    onActivated: function(index) { if (bound) map[key] = String(options[index]) }

    contentItem: TextInput {
        text: root.bound ? String(root.map[root.key] ?? "") : root.editText
        color: Theme.text
        selectionColor: Theme.selection
        selectedTextColor: Theme.text
        font: root.font
        verticalAlignment: Text.AlignVCenter
        clip: true
        autoScroll: true
        onTextEdited: if (root.bound) root.map[root.key] = text
    }
    background: Rectangle {
        radius: Theme.radiusSmall
        color: Theme.field
        border.color: root.activeFocus ? Theme.accent : Theme.border
    }
    indicator: Item {
        x: root.width - width
        width: 32; height: root.height
        Icon { anchors.centerIn: parent; path: Icons.chevronDown; color: Theme.muted; size: 16 }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.popup.visible ? root.popup.close() : root.popup.open() }
    }
    delegate: ItemDelegate {
        id: row
        required property int index
        required property var modelData
        width: root.width
        height: 30
        highlighted: root.highlightedIndex === index
        contentItem: Text {
            text: row.modelData
            color: Theme.text
            font.family: Theme.font
            font.pixelSize: Theme.size
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            leftPadding: 4
        }
        background: Rectangle { color: row.highlighted ? Theme.cardRaised : "transparent" }
    }
    popup: Popup {
        y: root.height
        width: root.width
        implicitHeight: Math.min(list.contentHeight + 2, 300)
        padding: 1
        background: Rectangle { color: Theme.card; border.color: Theme.borderStrong }
        contentItem: ListView {
            id: list
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            ScrollBar.vertical: ScrollBar { }
        }
    }
}
