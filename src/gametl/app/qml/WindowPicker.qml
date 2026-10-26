import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

// The game window: a drop-down of the open windows (or a typed part of a
// title) and a Refresh button; the list is read when the row appears.
RowLayout {
    property int fieldWidth: 260
    spacing: Theme.space
    Component.onCompleted: backend.refreshWindows()
    Combo { key: "window_match"; options: backend.windows; implicitWidth: fieldWidth }
    SecondaryButton { text: "Refresh"; icon_: Icons.refresh; onClicked: backend.refreshWindows() }
}
