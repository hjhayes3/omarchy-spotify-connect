import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "hjhayes3.spotify-connect"
  ipcTarget: "hjhayes3.spotify-connect"

  property var devices: []
  property var activeDevice: null
  property bool authenticated: false
  property bool configured: false
  property bool busy: false
  property string errorText: ""
  property string errorKind: ""
  property string actionText: ""
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string helperPath: Qt.resolvedUrl("spotify-connect").toString().replace(/^file:\/\//, "")
  readonly property int refreshInterval: Math.max(10, parseInt(setting("refreshIntervalSec", 30), 10) || 30) * 1000

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function run(args, action) {
    if (backend.running) return
    busy = true
    actionText = action || ""
    errorText = ""
    backend.command = [helperPath].concat(args)
    backend.running = true
  }

  function refresh() { run(["status"], "Refreshing…") }
  function authenticate() { run(["auth"], "Waiting for Spotify authorization in your browser…") }
  function transfer(device) {
    if (!device || device.is_restricted) return
    run(["transfer", "--id", String(device.id)], "Transferring to " + String(device.name) + "…")
  }
  function remember(device) {
    if (!device) return
    run(["remember", "--id", String(device.id), "--name", String(device.name), "--type", String(device.type || "speaker")], "Remembering " + String(device.name) + "…")
  }
  function forget(device) {
    if (!device) return
    run(["forget", "--id", String(device.id)], "Forgetting " + String(device.name) + "…")
  }

  function applyResult(text, exitCode) {
    busy = false
    actionText = ""
    var value
    try { value = JSON.parse(String(text || "").trim()) }
    catch (e) {
      errorText = "Spotify helper returned invalid data"
      errorKind = "invalid_response"
      return
    }
    if (exitCode !== 0 || !value.ok) {
      errorText = String(value.error || "Spotify command failed")
      errorKind = String(value.kind || "error")
      if (value.kind === "not_authenticated" || value.kind === "auth_expired") authenticated = false
      return
    }
    errorKind = ""
    if (value.authenticated !== undefined) authenticated = value.authenticated === true
    if (value.configured !== undefined) configured = value.configured === true
    if (value.devices instanceof Array) devices = value.devices
    if (value.active_device !== undefined) activeDevice = value.active_device
    if (value.transferred) transferSettle.restart()
    if (value.remembered || value.forgotten) Qt.callLater(root.refresh)
  }

  onOpenedChanged: if (opened) refresh()
  Component.onCompleted: refresh()

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰓇"
    active: root.opened
    tooltipText: activeDevice ? "Spotify: " + activeDevice.name : "Spotify Connect"
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.MiddleButton) root.refresh()
      else root.toggle()
    }
  }

  PopupCard {
    id: popup
    anchorItem: button
    bar: root.bar
    owner: root
    open: root.opened
    contentWidth: fittedContentWidth(Style.space(310))
    contentHeight: fittedContentHeight(content.implicitHeight, Style.space(620))

    Flickable {
      anchors.fill: parent
      contentHeight: content.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds

      Column {
        id: content
        width: parent.width
        spacing: Style.space(12)

        RowLayout {
          width: parent.width
          Text {
            text: "Spotify"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
            Layout.fillWidth: true
          }
          PanelActionButton {
            iconText: root.busy ? "󰑓" : "󰑐"
            tooltipText: "Refresh Spotify Connect devices"
            foreground: root.foreground
            fontFamily: root.fontFamily
            enabled: !root.busy
            onClicked: root.refresh()
          }
        }

        PanelSeparator { width: parent.width; foreground: root.foreground }

        Text {
          visible: root.actionText !== ""
          width: parent.width
          text: root.actionText
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        Text {
          visible: root.errorText !== ""
          width: parent.width
          text: root.errorText + (root.errorKind === "rate_limited" ? " Try again after Spotify's cooldown." : "")
          color: root.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        Column {
          visible: !root.authenticated
          width: parent.width
          spacing: Style.space(10)
          Text {
            width: parent.width
            text: root.configured ? "Connect your Spotify account to list devices." : "Configure a Spotify application Client ID first."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.WordWrap
          }
          Button {
            visible: root.configured
            text: "Authenticate with Spotify"
            enabled: !root.busy
            onClicked: root.authenticate()
          }
        }

        Column {
          visible: root.authenticated
          width: parent.width
          spacing: Style.space(8)

          PanelSectionHeader {
            text: root.activeDevice ? "PLAYING ON" : "NO ACTIVE SPOTIFY SESSION"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Text {
            visible: root.devices.length === 0
            width: parent.width
            text: "No Spotify Connect devices are currently available. Open Spotify on a device, then refresh."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.WordWrap
          }

          Repeater {
            model: root.devices
            delegate: Rectangle {
              required property var modelData
              width: parent.width
              height: deviceContent.implicitHeight + Style.space(14)
              radius: Style.cornerRadius
              color: deviceMouse.containsMouse ? Style.hoverFillFor(root.foreground, Color.accent) : "transparent"
              opacity: modelData.is_restricted || !modelData.is_available ? 0.55 : 1.0

              RowLayout {
                id: deviceContent
                z: 2
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(8)
                anchors.rightMargin: Style.space(8)
                spacing: Style.space(8)
                Text {
                  text: modelData.is_active ? "●" : "○"
                  color: modelData.is_active ? Color.accent : root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                }
                ColumnLayout {
                  Layout.fillWidth: true
                  spacing: 0
                  Text {
                    Layout.fillWidth: true
                    text: String(modelData.name)
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: modelData.is_active
                    elide: Text.ElideRight
                  }
                  Text {
                    Layout.fillWidth: true
                    text: String(modelData.type || "device")
                      + (modelData.is_remembered ? (modelData.is_available ? " · remembered" : " · unavailable — activate in Spotify first") : "")
                      + (modelData.is_restricted ? " · restricted" : "")
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                  }
                }
                PanelActionButton {
                  iconText: modelData.is_remembered ? "󰆴" : "󰃃"
                  tooltipText: modelData.is_remembered ? "Forget cached device ID" : "Remember this device ID"
                  foreground: root.foreground
                  hoverColor: modelData.is_remembered ? root.urgent : root.foreground
                  fontFamily: root.fontFamily
                  enabled: !root.busy
                  onClicked: modelData.is_remembered ? root.forget(modelData) : root.remember(modelData)
                }
              }
              MouseArea {
                id: deviceMouse
                z: 1
                anchors.fill: parent
                hoverEnabled: true
                enabled: !root.busy && modelData.is_available && !modelData.is_restricted && !modelData.is_active
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: root.transfer(modelData)
              }
            }
          }
        }
      }
    }
  }

  Process {
    id: backend
    command: []
    stdout: StdioCollector { id: backendOut; waitForEnd: true }
    stderr: StdioCollector { waitForEnd: true }
    onExited: function(exitCode, _status) { root.applyResult(backendOut.text, exitCode) }
  }

  Timer { interval: root.refreshInterval; repeat: true; running: root.opened; onTriggered: if (!root.busy) root.refresh() }
  Timer { id: transferSettle; interval: 1200; repeat: false; onTriggered: root.refresh() }
}
