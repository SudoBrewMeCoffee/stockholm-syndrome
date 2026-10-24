// Stockholm — menu bar panel for stockholm-syndrome. SwiftUI, no dependencies.
// Build: ./build_app.sh    (swiftc, macOS 14+)
import SwiftUI
import AppKit

// MARK: - Model

struct PartState: Decodable { let available: Bool; let quote: String }
struct Store: Decodable, Identifiable {
    let name: String; let city: String; let postcode: String?; let phone: String?
    let distance_mi: Double?; let store_url: String?
    let parts: [String: PartState]
    var id: String { name + city }
    var inStock: [String] { parts.filter { $0.value.available }.map { $0.key }.sorted() }
}
struct Snapshot: Decodable {
    let checked_at: String
    let parts: [String]
    let part_names: [String: String]
    let plan_a: [String]?
    let buy_urls: [String: String]
    let launchd_label: String?
    let error: String?
    let stores: [String: Store]
}
struct HistoryRow: Identifiable {
    let id = UUID(); let when: Date; let store: String; let part: String; let inStock: Bool
}

let allParts: [(String, String, String)] = [   // part, capacity, colour
    ("MK2D4QN/A", "256GB", "Star White"), ("MK2E4QN/A", "256GB", "Night Sky"),
    ("MK2F4QN/A", "512GB", "Star White"), ("MK2G4QN/A", "512GB", "Night Sky"),
    ("MK2H4QN/A", "1TB",   "Star White"), ("MK2J4QN/A", "1TB",   "Night Sky"),
    ("MK2K4QN/A", "2TB",   "Star White"), ("MK2L4QN/A", "2TB",   "Night Sky"),
]

final class Watch: ObservableObject {
    static let shared = Watch()
    let repo: URL
    @Published var snap: Snapshot?
    @Published var history: [HistoryRow] = []
    @Published var now = Date()
    @Published var paused = false
    @Published var showAll = false
    @Published var showModels = false
    private var lastInStockKeys = Set<String>()
    private var timer: Timer?

    init() {
        let a = CommandLine.arguments
        repo = URL(fileURLWithPath: a.count > 1 ? a[1] : FileManager.default.currentDirectoryPath)
        reload()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.reload() }
    }

    var checkedAt: Date? { snap.flatMap { Watch.iso($0.checked_at) } }
    var stale: Bool { guard let c = checkedAt else { return true }; return now.timeIntervalSince(c) > 600 }
    var blocked: Bool { snap?.error != nil }
    var label: String { snap?.launchd_label ?? "com.stockholm.watch" }
    var inStockCount: Int { snap?.stores.values.reduce(0) { $0 + $1.inStock.count } ?? 0 }
    var near: [Store] { (snap?.stores.values.filter { $0.distance_mi != nil } ?? []).sorted { $0.distance_mi! < $1.distance_mi! } }
    var far: [Store] { (snap?.stores.values.filter { $0.distance_mi == nil } ?? []).sorted { $0.name < $1.name } }
    var hot: [Store] { (snap?.stores.values.filter { !$0.inStock.isEmpty } ?? []).sorted { ($0.distance_mi ?? 999) < ($1.distance_mi ?? 999) } }

    func reload() {
        now = Date()
        if let d = try? Data(contentsOf: repo.appendingPathComponent("snapshot.json")),
           let s = try? JSONDecoder().decode(Snapshot.self, from: d) {
            snap = s
            let keys = Set(s.stores.values.flatMap { st in st.inStock.map { st.id + $0 } })
            if !keys.subtracting(lastInStockKeys).isEmpty { NSSound(named: "Glass")?.play() }
            lastInStockKeys = keys
        }
        if let txt = try? String(contentsOf: repo.appendingPathComponent("history.csv"), encoding: .utf8) {
            history = txt.split(separator: "\n").dropFirst().compactMap { line in
                let f = line.split(separator: ",", omittingEmptySubsequences: false).map(String.init)
                guard f.count >= 5, let d = Watch.local(f[0]) else { return nil }
                return HistoryRow(when: d, store: f[3], part: f[4], inStock: f[1] == "appeared")
            }.reversed()
        }
        let p = repo.appendingPathComponent("paused").path
        paused = FileManager.default.fileExists(atPath: p)
    }

    func name(_ part: String) -> String { snap?.part_names[part] ?? allParts.first { $0.0 == part }.map { "iPhone Duo \($0.1) \($0.2)" } ?? part }
    func buyURL(_ part: String) -> URL? {
        if let u = snap?.buy_urls[part] { return URL(string: u) }
        guard let p = allParts.first(where: { $0.0 == part }) else { return nil }
        let cap = p.1.lowercased(), col = p.2.lowercased().replacingOccurrences(of: " ", with: "-")
        return URL(string: "https://www.apple.com/uk/shop/buy-iphone/iphone-duo/7.6-inch-display-\(cap)-\(col)")
    }

    var watched: [String] { snap?.parts ?? [] }
    var planA: [String] { snap?.plan_a ?? watched }
    func restartWatcher() {
        let t = Process(); t.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        t.arguments = ["kickstart", "-k", "gui/\(getuid())/\(label)"]; try? t.run()
    }
    func checkNow() { reload() }   // never forces an extra Apple request — every one counts against the quota
    func togglePause() {
        let p = repo.appendingPathComponent("paused")
        if paused { try? FileManager.default.removeItem(at: p) } else { FileManager.default.createFile(atPath: p.path, contents: nil) }
        reload()   // watcher polls the paused file every 5s
    }

    static func local(_ s: String) -> Date? {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm:ss"; f.timeZone = .current
        return f.date(from: s) ?? iso(s)
    }
    static func iso(_ s: String) -> Date? {
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime]
        if let d = f.date(from: s) { return d }
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return f.date(from: s)
    }
}

// MARK: - Views

func rel(_ d: Date, _ now: Date) -> String {
    let s = Int(now.timeIntervalSince(d))
    if s < 5 { return "just now" }; if s < 60 { return "\(s)s ago" }
    if s < 3600 { return "\(s/60)m ago" }
    let f = DateFormatter(); f.dateFormat = "EEE HH:mm"; return f.string(from: d)
}

struct Panel: View {
    @ObservedObject var w = Watch.shared

    var body: some View {
        VStack(spacing: 0) {
            Hero(w: w)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if !w.hot.isEmpty {
                        Section("In stock now", icon: "bolt.fill", tint: .green) {
                            ForEach(w.hot) { StoreRow(store: $0, w: w, highlight: true) }
                        }
                    }
                    Section("Near you", icon: "location.fill", tint: .blue) {
                        ForEach(w.near.prefix(12)) { StoreRow(store: $0, w: w) }
                    }
                    DisclosureGroup(isExpanded: $w.showAll) {
                        VStack(spacing: 2) { ForEach(w.near.dropFirst(8) + w.far) { StoreRow(store: $0, w: w) } }.padding(.top, 4)
                    } label: {
                        Label("Other stores (\(w.far.count))", systemImage: "map").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
                    }
                    DisclosureGroup(isExpanded: $w.showModels) {
                        ModelGrid(w: w).padding(.top, 6)
                    } label: {
                        Label("Watching \(w.watched.count) configs", systemImage: "list.bullet").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
                    }
                    Section("Restock history", icon: "clock.arrow.circlepath", tint: .orange) {
                        if w.history.isEmpty {
                            Text("No restocks seen yet — the watcher logs every in/out of stock it sees.").font(.caption).foregroundStyle(.tertiary)
                        } else {
                            ForEach(w.history.prefix(12)) { h in
                                HStack(spacing: 8) {
                                    Circle().fill(h.inStock ? Color.green : Color.gray.opacity(0.5)).frame(width: 7, height: 7)
                                    Text(rel(h.when, w.now)).font(.caption.monospacedDigit()).foregroundStyle(.secondary).frame(width: 70, alignment: .leading)
                                    Text(h.store).font(.caption.weight(.medium))
                                    Spacer()
                                    Text(w.name(h.part).replacingOccurrences(of: "iPhone Duo ", with: "")).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }.padding(14)
            }.frame(maxHeight: 460)
            Divider()
            Footer(w: w)
        }
        .frame(width: 380)
        .background(.regularMaterial)
    }
}

struct Hero: View {
    @ObservedObject var w: Watch
    var body: some View {
        let live = w.inStockCount > 0
        HStack(alignment: .center, spacing: 14) {
            ZStack {
                RoundedRectangle(cornerRadius: 14).fill(live ? Color.green.opacity(0.18) : Color.secondary.opacity(0.12)).frame(width: 52, height: 52)
                Image(systemName: "iphone.gen3").font(.system(size: 26, weight: .medium)).foregroundStyle(live ? Color.green : Color.secondary)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(w.watched.count == 1 ? w.name(w.watched[0]) : "iPhone Duo · \(w.watched.count) models").font(.headline)
                HStack(spacing: 6) {
                    Circle().fill(w.paused ? Color.orange : w.blocked ? Color.red : w.stale ? Color.red : live ? Color.green : Color.gray).frame(width: 8, height: 8)
                    Text(w.paused ? "Paused" : w.blocked ? "Apple blocking — backing off" : w.stale ? "Watcher not responding" : live ? "IN STOCK at \(w.hot.count) store\(w.hot.count == 1 ? "" : "s")" : "Nothing reservable · \(w.snap?.stores.count ?? 0) stores")
                        .font(.subheadline.weight(live ? .semibold : .regular)).foregroundStyle(live ? Color.green : Color.primary)
                }
                if let c = w.checkedAt { Text("Checked \(rel(c, w.now)) · ~1 request / 2½ min (Apple's limit)").font(.caption).foregroundStyle(.secondary) }
            }
            Spacer()
            if live, let first = w.hot.first?.inStock.first, let u = w.buyURL(first) {
                Button { NSWorkspace.shared.open(u) } label: { Label("Reserve", systemImage: "arrow.up.right.square.fill") }
                    .buttonStyle(.borderedProminent).tint(.green).controlSize(.large)
            }
        }.padding(16)
    }
}

struct Section<Content: View>: View {
    let title: String, icon: String, tint: Color, content: Content
    init(_ t: String, icon: String, tint: Color, @ViewBuilder c: () -> Content) { title = t; self.icon = icon; self.tint = tint; content = c() }
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(title, systemImage: icon).font(.subheadline.weight(.semibold)).foregroundStyle(tint).padding(.bottom, 2)
            content
        }
    }
}

struct StoreRow: View {
    let store: Store; @ObservedObject var w: Watch; var highlight = false
    var body: some View {
        let hit = !store.inStock.isEmpty
        HStack(spacing: 10) {
            Image(systemName: hit ? "checkmark.circle.fill" : "circle.dashed")
                .foregroundStyle(hit ? Color.green : Color.secondary.opacity(0.5)).font(.system(size: 15))
            VStack(alignment: .leading, spacing: 1) {
                Text(store.name).font(.callout.weight(hit ? .semibold : .regular))
                HStack(spacing: 6) {
                    Text(store.city).font(.caption).foregroundStyle(.secondary)
                    if let d = store.distance_mi { Text("· \(String(format: "%.0f", d)) mi").font(.caption).foregroundStyle(.secondary) }
                    if hit { Text("· " + store.inStock.map { w.name($0).replacingOccurrences(of: "iPhone Duo ", with: "") }.joined(separator: ", ")).font(.caption.weight(.medium)).foregroundStyle(.green) }
                }
            }
            Spacer()
            if hit, let u = w.buyURL(store.inStock[0]) {
                Button("Reserve") { NSWorkspace.shared.open(u) }.buttonStyle(.borderedProminent).tint(.green).controlSize(.small)
            } else if let p = store.phone, !p.isEmpty {
                Button { NSWorkspace.shared.open(URL(string: "tel:" + p.replacingOccurrences(of: " ", with: ""))!) } label: { Image(systemName: "phone") }
                    .buttonStyle(.borderless).foregroundStyle(.secondary).help("Call \(store.name) \(p)")
            }
        }
        .padding(.vertical, 5).padding(.horizontal, 8)
        .background(RoundedRectangle(cornerRadius: 8).fill(highlight ? Color.green.opacity(0.12) : Color.clear))
    }
}

struct ModelGrid: View {
    @ObservedObject var w: Watch
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(w.watched, id: \.self) { p in
                HStack(spacing: 8) {
                    Text(w.planA.contains(p) ? "A" : "B").font(.caption2.bold()).frame(width: 18, height: 18)
                        .background(Circle().fill(w.planA.contains(p) ? Color.green.opacity(0.25) : Color.orange.opacity(0.25)))
                    Text(w.name(p)).font(.callout)
                    Spacer()
                }
            }
            Text("Plan A alerts are loud; Plan B is the fallback. Edit STOCK_* env in the launchd plist to change.").font(.caption2).foregroundStyle(.tertiary).padding(.top, 4)
        }
    }
}

struct Footer: View {
    @ObservedObject var w: Watch
    var body: some View {
        HStack(spacing: 6) {
            Button { w.checkNow() } label: { Label("Refresh", systemImage: "arrow.clockwise") }
            Button { w.togglePause() } label: { Label(w.paused ? "Resume" : "Pause", systemImage: w.paused ? "play.fill" : "pause.fill") }
            Button { NSWorkspace.shared.open(w.repo.appendingPathComponent("duo_watch.log")) } label: { Label("Log", systemImage: "doc.text") }
            Spacer()
            Button { NSApp.terminate(nil) } label: { Image(systemName: "power") }.help("Quit Stockholm panel")
        }
        .buttonStyle(.borderless).controlSize(.small).font(.caption)
        .padding(.horizontal, 14).padding(.vertical, 10)
    }
}

// MARK: - App

func menuIcon(live: Bool) -> NSImage {
    let name = live ? "MenuIconLive" : "MenuIcon"
    if let url = Bundle.main.url(forResource: name, withExtension: "png"), let img = NSImage(contentsOf: url) {
        img.isTemplate = true   // adapts to light/dark menu bar
        img.size = NSSize(width: 18, height: 18)
        return img
    }
    return NSImage(systemSymbolName: "iphone.gen3", accessibilityDescription: nil)!
}

@main
struct StockholmApp: App {
    @ObservedObject var w = Watch.shared
    var body: some Scene {
        MenuBarExtra {
            Panel()
        } label: {
            let live = w.inStockCount > 0
            HStack(spacing: 3) {
                Image(nsImage: menuIcon(live: live))
                if live { Text("\(w.hot.count)").font(.caption.bold()) }
                else if w.paused { Text("⏸").font(.caption2) }
                else if w.blocked { Text("…").font(.caption.bold()) }
                else if w.stale { Text("!").font(.caption.bold()) }
            }
        }
        .menuBarExtraStyle(.window)
    }
}
