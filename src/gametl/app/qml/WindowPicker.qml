import QtQuick
import QtQuick.Layouts
import "Icons.js" as Icons

// The game window: a drop-down of the open windows (or a typed part of a
// title) and a Refresh button; the list is read when the row appears. A
// typed title is written once the typing is done: a running overlay
// restarts on it.
RowLayout {
    spacing: Theme.space
    Component.onCompleted: backend.refreshWindows()
    Combo { key: "window_match"; options: backend.windows; editable: true; live: false }
    SecondaryButton { text: "Refresh"; icon_: Icons.refresh; onClicked: backend.refreshWindows() }
}
