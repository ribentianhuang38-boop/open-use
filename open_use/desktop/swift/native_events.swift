import Foundation
import AppKit
import CoreGraphics

func printUsage() -> Never {
    print("""
    Usage:
      native_events click <x> <y>
      native_events double_click <x> <y>
      native_events right_click <x> <y>
      native_events drag <x1> <y1> <x2> <y2>
      native_events scroll <x> <y> <delta>
      native_events copy_file <file_path>
      native_events type_text <text>
      native_events key_code <code>
    """)
    exit(1)
}

let args = CommandLine.arguments
guard args.count >= 2 else { printUsage() }
let cmd = args[1]

switch cmd {
case "click":
    guard args.count >= 4, let x = Double(args[2]), let y = Double(args[3]) else { printUsage() }
    let pt = CGPoint(x: x, y: y)
    guard let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: pt, mouseButton: .left),
          let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: pt, mouseButton: .left) else { exit(1) }
    down.post(tap: .cghidEventTap)
    usleep(25000)
    up.post(tap: .cghidEventTap)

case "double_click":
    guard args.count >= 4, let x = Double(args[2]), let y = Double(args[3]) else { printUsage() }
    let pt = CGPoint(x: x, y: y)
    guard let down1 = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: pt, mouseButton: .left),
          let up1 = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: pt, mouseButton: .left),
          let down2 = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: pt, mouseButton: .left),
          let up2 = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: pt, mouseButton: .left) else { exit(1) }
    down1.setIntegerValueField(.mouseEventClickState, value: 1)
    up1.setIntegerValueField(.mouseEventClickState, value: 1)
    down2.setIntegerValueField(.mouseEventClickState, value: 2)
    up2.setIntegerValueField(.mouseEventClickState, value: 2)
    down1.post(tap: .cghidEventTap)
    usleep(20000)
    up1.post(tap: .cghidEventTap)
    usleep(50000)
    down2.post(tap: .cghidEventTap)
    usleep(20000)
    up2.post(tap: .cghidEventTap)

case "right_click":
    guard args.count >= 4, let x = Double(args[2]), let y = Double(args[3]) else { printUsage() }
    let pt = CGPoint(x: x, y: y)
    guard let down = CGEvent(mouseEventSource: nil, mouseType: .rightMouseDown, mouseCursorPosition: pt, mouseButton: .right),
          let up = CGEvent(mouseEventSource: nil, mouseType: .rightMouseUp, mouseCursorPosition: pt, mouseButton: .right) else { exit(1) }
    down.post(tap: .cghidEventTap)
    usleep(25000)
    up.post(tap: .cghidEventTap)

case "drag":
    guard args.count >= 6, let x1 = Double(args[2]), let y1 = Double(args[3]),
          let x2 = Double(args[4]), let y2 = Double(args[5]) else { printUsage() }
    let pt1 = CGPoint(x: x1, y: y1)
    let pt2 = CGPoint(x: x2, y: y2)
    guard let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: pt1, mouseButton: .left) else { exit(1) }
    down.post(tap: .cghidEventTap)
    usleep(50000)
    let steps = 15
    for i in 1...steps {
        let curX = x1 + (x2 - x1) * Double(i) / Double(steps)
        let curY = y1 + (y2 - y1) * Double(i) / Double(steps)
        let curPt = CGPoint(x: curX, y: curY)
        if let drag = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDragged, mouseCursorPosition: curPt, mouseButton: .left) {
            drag.post(tap: .cghidEventTap)
            usleep(15000)
        }
    }
    if let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: pt2, mouseButton: .left) {
        up.post(tap: .cghidEventTap)
    }

case "scroll":
    guard args.count >= 5, let x = Double(args[2]), let y = Double(args[3]),
          let delta = Int32(args[4]) else { printUsage() }
    let pt = CGPoint(x: x, y: y)
    if let move = CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: pt, mouseButton: .left) {
        move.post(tap: .cghidEventTap)
    }
    for _ in 0..<8 {
        if let scroll = CGEvent(scrollWheelEvent2Source: nil, units: .line, wheelCount: 1, wheel1: delta, wheel2: 0, wheel3: 0) {
            scroll.location = pt
            scroll.post(tap: .cghidEventTap)
        }
        usleep(16000)
    }

case "copy_file":
    guard args.count >= 3 else { printUsage() }
    let filePath = args[2]
    let pb = NSPasteboard.general
    pb.clearContents()
    let url = URL(fileURLWithPath: filePath)
    if let img = NSImage(contentsOfFile: filePath) {
        pb.writeObjects([img, url as NSPasteboardWriting])
        print("Mounted image and file to pasteboard: \(filePath)")
    } else {
        pb.writeObjects([url as NSPasteboardWriting])
        print("Mounted file to pasteboard: \(filePath)")
    }

case "type_text":
    guard args.count >= 3 else { printUsage() }
    // Join all remaining args (in case text has spaces)
    let text = args[2...].joined(separator: " ")
    let src = CGEventSource(stateID: .hidSystemState)
    for ch in text.utf16 {
        var uchar = ch
        if let keyDown = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: true) {
            keyDown.keyboardSetUnicodeString(stringLength: 1, unicodeString: &uchar)
            keyDown.post(tap: .cghidEventTap)
        }
        if let keyUp = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: false) {
            keyUp.keyboardSetUnicodeString(stringLength: 1, unicodeString: &uchar)
            keyUp.post(tap: .cghidEventTap)
        }
        usleep(8000) // 8ms between chars for reliability
    }

case "key_code":
    guard args.count >= 3, let code = UInt16(args[2]) else { printUsage() }
    let src = CGEventSource(stateID: .hidSystemState)
    if let keyDown = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true),
       let keyUp = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false) {
        keyDown.post(tap: .cghidEventTap)
        usleep(25000)
        keyUp.post(tap: .cghidEventTap)
    }

default:
    printUsage()
}
