import QtQuick

// The keyboard-focus outline, drawn just outside the control it sits in.
// Fields show focus with their accent edge instead; this is for buttons,
// switches, segments, steppers and sliders.
Rectangle {
    property real gap: 3
    anchors.fill: parent
    anchors.margins: -gap
    radius: Theme.radius + gap
    color: "transparent"
    border.color: Theme.accent
    border.width: 2
}
