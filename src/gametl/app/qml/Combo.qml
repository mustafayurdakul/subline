import QtQuick
import QtQuick.Controls.Basic
import "Icons.js" as Icons

// A drop-down bound to `map[key]`: pick one of `options`, or type a value
// when `editable`. `fontPreview` draws each option in the font it names.
ComboBox {
    id: root
    property var options: []
    property var map: backend.settings
    property string key: ""
    property bool fontPreview: false

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
    onActivated: function(index) { map[key] = String(options[index]) }

    contentItem: TextInput {
        enabled: root.editable  // a disabled input lets the press through to the box, which opens the list
        text: String(root.map[root.key] ?? "")
        color: Theme.text
        selectionColor: Theme.selection
        selectedTextColor: Theme.text
        font: root.font
        verticalAlignment: Text.AlignVCenter
        clip: true
        autoScroll: true
        onTextEdited: root.map[root.key] = text
    }
    background: Rectangle {
        radius: Theme.radius
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
        contentItem: Label {
            text: row.modelData
            font.family: root.fontPreview ? row.modelData : Theme.font
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
