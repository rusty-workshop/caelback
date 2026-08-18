// caelback panel -- a tiny, self-contained quickshell config, independent of
// Caelestia's own shell (which lives at /etc/xdg/quickshell/caelestia). Run
// standalone via `qs -c caelback-panel`, toggled by a keybind script that
// kills it if already running, or launches it if not -- so there's no
// in-app show/hide state to manage here, just "exist" or "don't".
//
// Deliberately doesn't do restore from here: that needs confirmation,
// sometimes a sudo prompt, and can legitimately fail partway -- exactly the
// kind of thing that belongs in a terminal you can actually watch, not a
// one-click GUI button. This panel only lists snapshots and lets you star
// one; `caelback restore` stays a deliberate terminal action.

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

ShellRoot {
    id: root

    readonly property string caelbackBin: `${Quickshell.env("HOME")}/.local/bin/caelback`
    property var snapshots: []
    property bool busy: false
    property string starTarget: ""
    property string diffText: ""
    property bool diffOpen: false

    function refresh(): void {
        listProc.running = false
        listProc.running = true
    }

    Process {
        id: listProc
        command: [root.caelbackBin, "list", "--json"]
        stdout: StdioCollector {
            id: listCollector
            onDataChanged: {
                try {
                    root.snapshots = JSON.parse(listCollector.text)
                } catch (e) {
                    root.snapshots = []
                }
            }
        }
    }

    Process {
        id: snapshotProc
        command: [root.caelbackBin, "snapshot"]
        stdout: StdioCollector {}
        onExited: {
            root.busy = false
            root.refresh()
        }
    }

    Process {
        id: starProc
        command: [root.caelbackBin, "star", root.starTarget]
        stdout: StdioCollector {}
        onExited: {
            root.busy = false
            root.refresh()
        }
    }

    Process {
        id: diffProc
        stdout: StdioCollector {
            id: diffCollector
            onDataChanged: {
                root.diffText = diffCollector.text
                root.diffOpen = true
                root.busy = false
            }
        }
    }

    function takeSnapshot(): void {
        if (root.busy)
            return
        root.busy = true
        snapshotProc.running = true
    }

    function starSnapshot(name: string): void {
        if (root.busy)
            return
        root.busy = true
        root.starTarget = name
        starProc.running = true
    }

    function showDiff(prevName: string, thisName: string): void {
        if (root.busy)
            return
        root.busy = true
        diffProc.command = [root.caelbackBin, "diff", prevName, thisName]
        diffProc.running = true
    }

    Component.onCompleted: refresh()

    FloatingWindow {
        id: win
        visible: true
        title: "caelback"
        implicitWidth: 420
        implicitHeight: 480
        color: "#1e1e2e"

        Item {
            anchors.fill: parent
            focus: true
            Keys.onEscapePressed: Qt.quit()
            Component.onCompleted: forceActiveFocus()

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "caelback"
                        color: "#cdd6f4"
                        font.pixelSize: 20
                        font.bold: true
                        Layout.fillWidth: true
                    }

                    Rectangle {
                        implicitWidth: snapshotLabel.implicitWidth + 20
                        implicitHeight: 32
                        radius: 8
                        color: snapshotArea.containsMouse ? "#45475a" : "#313244"
                        opacity: root.busy ? 0.5 : 1

                        Text {
                            id: snapshotLabel
                            anchors.centerIn: parent
                            text: root.busy ? "…" : "Snapshot now"
                            color: "#cdd6f4"
                            font.pixelSize: 12
                        }

                        MouseArea {
                            id: snapshotArea
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: !root.busy
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.takeSnapshot()
                        }
                    }
                }

                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: root.snapshots
                    spacing: 6

                    delegate: Rectangle {
                        id: row
                        required property var modelData
                        required property int index
                        width: ListView.view.width
                        height: 56
                        radius: 8
                        color: modelData.starred ? "#313244" : "#181825"
                        border.color: modelData.starred ? "#f9e2af" : "transparent"
                        border.width: 1

                        MouseArea {
                            anchors.fill: parent
                            enabled: !row.modelData.starred && !root.busy
                            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: root.starSnapshot(row.modelData.name)
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 10

                            Text {
                                text: row.modelData.starred ? "★" : "☆"
                                color: row.modelData.starred ? "#f9e2af" : "#6c7086"
                                font.pixelSize: 16
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text {
                                    text: row.modelData.name
                                    color: "#cdd6f4"
                                    font.pixelSize: 13
                                }
                                Text {
                                    text: `${row.modelData.size_human} · ${row.modelData.package_count} pkgs`
                                    color: "#a6adc8"
                                    font.pixelSize: 11
                                }
                            }

                            Rectangle {
                                visible: row.index > 0
                                implicitWidth: 28
                                implicitHeight: 28
                                radius: 6
                                color: diffArea.containsMouse ? "#45475a" : "transparent"

                                Text {
                                    anchors.centerIn: parent
                                    text: "⇄"
                                    color: "#a6adc8"
                                    font.pixelSize: 14
                                }

                                MouseArea {
                                    id: diffArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    enabled: !root.busy
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.showDiff(root.snapshots[row.index - 1].name, row.modelData.name)
                                }
                            }
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: root.snapshots.length === 0
                        ? "No snapshots yet."
                        : "Click a snapshot to star it, ⇄ to diff it against the one before. Restore stays in the terminal (caelback restore) -- it needs confirmation and sometimes sudo."
                    color: "#6c7086"
                    font.pixelSize: 10
                    wrapMode: Text.WordWrap
                }
            }

            Rectangle {
                anchors.fill: parent
                visible: root.diffOpen
                color: "#cc11111b"

                MouseArea {
                    anchors.fill: parent
                    onClicked: root.diffOpen = false
                }

                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width - 40
                    height: parent.height - 60
                    radius: 10
                    color: "#1e1e2e"
                    border.color: "#45475a"
                    border.width: 1

                    MouseArea {
                        // Eats clicks so they don't fall through to the overlay's
                        // close-on-click-outside handler underneath.
                        anchors.fill: parent
                    }

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 8

                        RowLayout {
                            Layout.fillWidth: true

                            Text {
                                text: "Diff"
                                color: "#cdd6f4"
                                font.pixelSize: 14
                                font.bold: true
                                Layout.fillWidth: true
                            }

                            Rectangle {
                                implicitWidth: 24
                                implicitHeight: 24
                                radius: 6
                                color: closeArea.containsMouse ? "#45475a" : "transparent"

                                Text {
                                    anchors.centerIn: parent
                                    text: "✕"
                                    color: "#a6adc8"
                                    font.pixelSize: 12
                                }

                                MouseArea {
                                    id: closeArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.diffOpen = false
                                }
                            }
                        }

                        Flickable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            contentWidth: width
                            contentHeight: diffOutput.implicitHeight

                            Text {
                                id: diffOutput
                                width: parent.width
                                text: root.diffText || "No differences."
                                color: "#cdd6f4"
                                font.family: "monospace"
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                            }
                        }
                    }
                }
            }
        }
    }
}
