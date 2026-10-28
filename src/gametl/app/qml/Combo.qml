import QtQuick
import QtQuick.Controls.Basic as C
import "Icons.js" as Icons

// A drop-down bound to `map[key]`: pick one of `options`, or, when
// `editable`, type a value. With `values`, the options are labels and the
// matching value is what gets written. `fontPreview` draws each option in
// the font it names. `live: false` writes typed text only when the typing
// is done (Enter, or leaving the field), as Field does.
C.ComboBox {
    id: root
    property var options: []
    property var values: []  // empty: the options are the values
    property var map: backend.settings
    property string key: ""
    property bool fontPreview: false
    property bool live: true

    editable: false
    model: options
    implicitWidth: 260
    implicitHeight: Theme.controlHeight
    leftPadding: 12
    rightPadding: 36
    font.family: Theme.font
    font.pixelSize: Theme.size
    opacity: enabled ? 1 : Theme.disabledOpacity

    // The list follows the map, so the open list and the arrow keys start
    // from the value in force. A model reset (the window list refreshing)
    // moves the index itself, so the binding is put back after one.
    function indexOfValue(value) { return (values.length ? values : options).indexOf(value) }
    currentIndex: indexOfValue(map[key])
    onCountChanged: currentIndex = Qt.binding(function() { return root.indexOfValue(root.map[root.key]) })

    // The text comes from the map, not from editText: a model reset blanks
    // editText, and must not blank the field.
    onActivated: function(index) { map[key] = String(values.length ? values[index] : options[index]) }
    function shown(value) {
        const i = values.indexOf(value)
        return i >= 0 ? String(options[i]) : String(value ?? "")
    }

    contentItem: TextInput {
        enabled: root.editable  // a disabled input lets the press through to the box, which opens the list
        text: root.shown(root.map[root.key])
        color: Theme.text
        selectionColor: Theme.selection
        selectedTextColor: Theme.text
        font: root.font
        verticalAlignment: Text.AlignVCenter
        clip: true
        autoScroll: true
        onTextEdited: if (root.live) root.map[root.key] = text
        onEditingFinished: if (!root.live && String(root.map[root.key] ?? "") !== text) root.map[root.key] = text
    }
    background: Rectangle {
        radius: Theme.radius
        color: root.pressed ? Theme.cardPressed : root.hovered && !root.editable ? Theme.cardRaised : Theme.field
        border.color: root.activeFocus ? Theme.accent : root.hovered ? Theme.borderHover : Theme.borderStrong
        border.width: root.activeFocus ? 2 : 1
    }
    indicator: Item {
        x: root.width - width
        width: 32; height: root.height
        Icon { anchors.centerIn: parent; path: Icons.chevronDown; color: Theme.muted; size: 16 }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.popup.visible ? root.popup.close() : root.popup.open() }
    }
    delegate: C.ItemDelegate {
        id: row
        required property int index
        required property var modelData
        width: root.width
        height: Theme.controlHeight
        highlighted: root.highlightedIndex === index
        contentItem: Label {
            text: row.modelData
            font.family: root.fontPreview ? row.modelData : Theme.font
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            leftPadding: 4
        }
        background: Rectangle {
            color: row.down ? Theme.cardPressed : row.highlighted ? Theme.accentSoft : row.hovered ? Theme.cardRaised : "transparent"
        }
    }
    popup: C.Popup {
        // Below the box, or above it when the window has no room below. Worked
        // out here, not left to the popup's own flip, which counts the page's
        // scale twice and leaves the list floating far above the box. Read
        // again at each opening (`visible`), as the page may have scrolled.
        y: {
            const below = root.height + 2
            if (!visible)
                return below
            const bottom = root.mapToItem(null, 0, below).y + height * uiScale
            return bottom > root.Window.height ? -(height + 2) : below
        }
        width: root.width
        implicitHeight: Math.min(list.contentHeight + 2, 300)
        padding: 1
        // The page is scaled for the screen as a whole, but a popup is drawn
        // above it, so it takes the same scale itself, growing from its corner.
        scale: uiScale
        transformOrigin: C.Popup.TopLeft
        background: Rectangle { radius: Theme.radius; color: Theme.card; border.color: Theme.borderStrong }
        contentItem: ListView {
            id: list
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            C.ScrollBar.vertical: ThinScrollBar { }
        }
    }
}
