#[cfg(target_os = "macos")]
mod macos {
    use core_foundation::base::{CFType, CFTypeRef, TCFType};
    use core_foundation::dictionary::CFDictionary;
    use core_foundation::number::CFNumber;
    use core_foundation::string::{CFString, CFStringRef};
    use core_graphics::geometry::CGRect;
    use core_graphics::window::{
        copy_window_info, kCGNullWindowID, kCGWindowAlpha, kCGWindowBounds, kCGWindowLayer,
        kCGWindowListExcludeDesktopElements, kCGWindowListOptionOnScreenOnly, kCGWindowName,
        kCGWindowOwnerPID,
    };
    use objc2_app_kit::NSRunningApplication;
    use serde::Serialize;
    use std::ffi::c_void;

    const EXPECTED_BUNDLE_IDENTIFIER: &str = "com.irodori-scena.dev";
    const EXPECTED_WINDOW_TITLE: &str = "irodori SCENA [DEV]";

    #[derive(Serialize)]
    #[serde(rename_all = "camelCase")]
    struct ProbeResult {
        bundle_identifier: &'static str,
        pid: i32,
        visible: bool,
        window_bounds: WindowBounds,
        window_title: &'static str,
    }

    #[derive(Serialize)]
    struct WindowBounds {
        height: f64,
        width: f64,
        x: f64,
        y: f64,
    }

    fn field(dictionary: &CFDictionary, key: CFStringRef) -> Option<CFType> {
        let raw = dictionary.find(key as *const c_void)?;
        Some(unsafe { CFType::wrap_under_get_rule(*raw as CFTypeRef) })
    }

    fn string_field(dictionary: &CFDictionary, key: CFStringRef) -> Option<String> {
        field(dictionary, key)?
            .downcast::<CFString>()
            .map(|value| value.to_string())
    }

    fn number_field(dictionary: &CFDictionary, key: CFStringRef) -> Option<f64> {
        field(dictionary, key)?.downcast::<CFNumber>()?.to_f64()
    }

    fn candidate(dictionary: &CFDictionary) -> Option<ProbeResult> {
        if string_field(dictionary, unsafe { kCGWindowName })? != EXPECTED_WINDOW_TITLE
            || number_field(dictionary, unsafe { kCGWindowLayer })? != 0.0
            || number_field(dictionary, unsafe { kCGWindowAlpha })? <= 0.0
        {
            return None;
        }
        let pid = number_field(dictionary, unsafe { kCGWindowOwnerPID })? as i32;
        let application = NSRunningApplication::runningApplicationWithProcessIdentifier(pid)?;
        if application.bundleIdentifier()?.to_string() != EXPECTED_BUNDLE_IDENTIFIER {
            return None;
        }
        let bounds = field(dictionary, unsafe { kCGWindowBounds })?
            .downcast::<CFDictionary>()
            .and_then(|value| CGRect::from_dict_representation(&value))?;
        if bounds.size.width <= 0.0 || bounds.size.height <= 0.0 {
            return None;
        }
        Some(ProbeResult {
            bundle_identifier: EXPECTED_BUNDLE_IDENTIFIER,
            pid,
            visible: true,
            window_bounds: WindowBounds {
                height: bounds.size.height,
                width: bounds.size.width,
                x: bounds.origin.x,
                y: bounds.origin.y,
            },
            window_title: EXPECTED_WINDOW_TITLE,
        })
    }

    pub fn run() -> Result<String, String> {
        let window_list = copy_window_info(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        )
        .ok_or_else(|| "CoreGraphics returned no window list".to_owned())?;
        let mut matches = window_list.get_all_values().into_iter().filter_map(|raw| {
            let value = unsafe { CFType::wrap_under_get_rule(raw as CFTypeRef) };
            value
                .downcast::<CFDictionary>()
                .and_then(|dictionary| candidate(&dictionary))
        });
        let result = matches.next().ok_or_else(|| {
            format!("no visible {EXPECTED_BUNDLE_IDENTIFIER} window titled {EXPECTED_WINDOW_TITLE}")
        })?;
        if matches.next().is_some() {
            return Err(format!(
                "multiple visible {EXPECTED_BUNDLE_IDENTIFIER} windows matched"
            ));
        }
        serde_json::to_string(&result).map_err(|error| error.to_string())
    }
}

fn main() {
    #[cfg(target_os = "macos")]
    match macos::run() {
        Ok(result) => println!("{result}"),
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(1);
        }
    }

    #[cfg(not(target_os = "macos"))]
    {
        eprintln!("development app verification is not implemented for this platform yet");
        std::process::exit(1);
    }
}
