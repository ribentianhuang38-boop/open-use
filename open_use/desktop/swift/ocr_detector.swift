import Foundation
import ImageIO
import Vision

let args = CommandLine.arguments
guard args.count > 1 else {
    fputs("Usage: ocr_detector <image_path> [scale_factor]\n", stderr)
    exit(1)
}

let imagePath = args[1]
let scale: Double = (args.count > 2 ? Double(args[2]) : nil) ?? 1.0
let url = URL(fileURLWithPath: imagePath)

guard let imageSource = CGImageSourceCreateWithURL(url as CFURL, nil),
      let cgImage = CGImageSourceCreateImageAtIndex(imageSource, 0, nil) else {
    fputs("Failed to load image: \(imagePath)\n", stderr)
    exit(1)
}

let width = Double(cgImage.width)
let height = Double(cgImage.height)

// 1. Accurate Multi-language OCR Request
let textRequest = VNRecognizeTextRequest()
textRequest.recognitionLevel = .accurate
textRequest.usesLanguageCorrection = true
textRequest.recognitionLanguages = ["zh-Hans", "zh-Hant", "en-US"]

// 2. UI Rectangle & Container Detection Request
let rectRequest = VNDetectRectanglesRequest()
rectRequest.minimumConfidence = 0.5
rectRequest.minimumSize = 0.008
rectRequest.maximumObservations = 40

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([textRequest, rectRequest])
    
    struct DetectedBox {
        var x: Int
        var y: Int
        var w: Int
        var h: Int
        var text: String
        var isContainer: Bool
    }
    
    var boxes: [DetectedBox] = []
    
    // Process UI Rectangles first
    var rectBoxes: [(x: Int, y: Int, w: Int, h: Int)] = []
    if let rectResults = rectRequest.results {
        for r in rectResults {
            let b = r.boundingBox
            let rx = Int((b.minX * width) / scale)
            let ry = Int(((1.0 - b.maxY) * height) / scale)
            let rw = Int((b.width * width) / scale)
            let rh = Int((b.height * height) / scale)
            if rw > 10 && rh > 10 && rw < Int(width * 0.95 / scale) {
                rectBoxes.append((rx, ry, rw, rh))
            }
        }
    }
    
    // Process Text Elements and link with containing rects
    var matchedRects = Set<Int>()
    if let textResults = textRequest.results {
        for obs in textResults {
            guard let candidate = obs.topCandidates(1).first else { continue }
            let text = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
            if text.isEmpty { continue }
            
            let b = obs.boundingBox
            var tx = Int((b.minX * width) / scale)
            var ty = Int(((1.0 - b.maxY) * height) / scale)
            var tw = Int((b.width * width) / scale)
            var th = Int((b.height * height) / scale)
            
            // If contained inside a small-to-medium button/input rect, expand bbox to container
            for (idx, rect) in rectBoxes.enumerated() {
                if tx >= rect.x - 5 && ty >= rect.y - 5 &&
                   (tx + tw) <= (rect.x + rect.w + 5) && (ty + th) <= (rect.y + rect.h + 5) {
                    if rect.w <= 400 && rect.h <= 100 {
                        tx = rect.x
                        ty = rect.y
                        tw = rect.w
                        th = rect.h
                        matchedRects.insert(idx)
                        break
                    }
                }
            }
            boxes.append(DetectedBox(x: tx, y: ty, w: tw, h: th, text: text, isContainer: false))
        }
    }
    
    // Add standalone UI containers (icons, search bars, buttons without text)
    for (idx, rect) in rectBoxes.enumerated() {
        if !matchedRects.contains(idx) && rect.w <= 500 && rect.h <= 120 {
            boxes.append(DetectedBox(x: rect.x, y: rect.y, w: rect.w, h: rect.h, text: "[UI_CONTAINER]", isContainer: true))
        }
    }
    
    // Output formatted lines
    var count = 0
    for box in boxes {
        count += 1
        print("\(count)|\(box.x)|\(box.y)|\(box.w)|\(box.h)|\(box.text)")
    }
} catch {
    fputs("Detection failed: \(error)\n", stderr)
    exit(1)
}
