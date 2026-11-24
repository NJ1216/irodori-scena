import Foundation

let info = ProcessInfo.processInfo
let names = ["nominal", "fair", "serious", "critical"]
let raw = info.thermalState.rawValue
let state = raw >= 0 && raw < names.count ? names[raw] : "unknown"
let payload: [String: Any] = [
    "state": state,
    "rawValue": raw,
    "lowPowerMode": info.isLowPowerModeEnabled,
    "activeProcessorCount": info.activeProcessorCount,
    "systemUptimeSeconds": info.systemUptime,
]
let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
print(String(decoding: data, as: UTF8.self))
