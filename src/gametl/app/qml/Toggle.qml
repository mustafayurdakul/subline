import QtQuick
import QtQuick.Controls.Basic as C

// A switch as Windows 11 draws one: off is an outlined track with a dark
// round knob, on is the accent with a white knob; the knob grows under the
// mouse. With a `key` it follows and writes that settings entry; without
// one the page binds `checked` itself.
C.Switch {
    id: root
    property var map: backend.settings
    property string key: ""
    readonly property bool bound: key !== ""

    implicitWidth: 40
    implicitHeight: 20
    padding: 0
    opacity: enabled ? 1 : Theme.disabledOpacity

    Binding on checked { when: root.bound; value: root.bound ? Boolean(root.map[root.key]) : false }
    onToggled: if (bound) map[key] = checked

    indicator: Rectangle {
        width: 40; height: 20
        radius: 10
        color: root.checked ? (root.down ? Qt.darker(Theme.accent, 1.2) : root.hovered ? Qt.lighter(Theme.accent, 1.1) : Theme.accent)
                            : (root.down ? Theme.cardPressed : root.hovered ? Theme.cardRaised : Theme.card)
        border.color: root.checked ? color : Theme.muted
        border.width: 1
        Behavior on color { ColorAnimation { duration: 120 } }

        Rectangle {
            readonly property int size: root.hovered || root.down ? 14 : 12
            width: root.down ? size + 3 : size
            height: size
            radius: size / 2
            y: (parent.height - height) / 2
            x: root.checked ? parent.width - width - (parent.height - size) / 2 : (parent.height - size) / 2
            color: root.checked ? Theme.textOnAccent : Theme.textSoft
            Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
        FocusRing { visible: root.visualFocus; radius: parent.radius + gap }
    }
    contentItem: Item {}
}
