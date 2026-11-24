use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AcceleratorTopology {
    pub kind: &'static str,
    pub adapter_id: Option<String>,
    pub dedicated_bytes: Option<u64>,
    pub dedicated_used_bytes: Option<u64>,
    pub gpu_utilization_percent: Option<f64>,
}

impl AcceleratorTopology {
    #[cfg(any(test, not(all(target_os = "macos", target_arch = "aarch64"))))]
    fn system_only() -> Self {
        Self {
            kind: "system-only",
            adapter_id: None,
            dedicated_bytes: None,
            dedicated_used_bytes: None,
            gpu_utilization_percent: None,
        }
    }
}

#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
pub fn detect() -> AcceleratorTopology {
    // Apple Silicon Metal devices use the physical-memory pool shared with the CPU.
    AcceleratorTopology {
        kind: "unified",
        adapter_id: Some("metal-default".into()),
        dedicated_bytes: None,
        dedicated_used_bytes: None,
        gpu_utilization_percent: None,
    }
}

#[cfg(all(target_os = "macos", not(target_arch = "aarch64")))]
pub fn detect() -> AcceleratorTopology {
    AcceleratorTopology::system_only()
}

#[cfg(not(any(target_os = "macos", windows)))]
pub fn detect() -> AcceleratorTopology {
    AcceleratorTopology::system_only()
}

#[cfg(windows)]
pub fn detect() -> AcceleratorTopology {
    use windows::Win32::Foundation::{FreeLibrary, HMODULE};
    use windows::Win32::Graphics::Dxgi::{
        CreateDXGIFactory1, IDXGIFactory1, DXGI_ADAPTER_FLAG_SOFTWARE,
    };
    use windows::Win32::System::LibraryLoader::LoadLibraryW;

    // A display adapter is not necessarily usable for SCENA inference.
    let cuda =
        unsafe { LoadLibraryW(windows::core::w!("nvcuda.dll")) }.unwrap_or(HMODULE::default());
    if cuda.is_invalid() {
        return AcceleratorTopology::system_only();
    }
    unsafe {
        let _ = FreeLibrary(cuda);
    }

    let Ok(factory) = (unsafe { CreateDXGIFactory1::<IDXGIFactory1>() }) else {
        return AcceleratorTopology::system_only();
    };
    let mut best: Option<AcceleratorTopology> = None;
    for index in 0.. {
        let Ok(adapter) = (unsafe { factory.EnumAdapters1(index) }) else {
            break;
        };
        let Ok(desc) = (unsafe { adapter.GetDesc1() }) else {
            continue;
        };
        if desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE.0 as u32 != 0
            || desc.VendorId != 0x10de
            || desc.DedicatedVideoMemory == 0
        {
            continue;
        }
        let bytes = desc.DedicatedVideoMemory as u64;
        if best
            .as_ref()
            .and_then(|item| item.dedicated_bytes)
            .is_some_and(|current| current >= bytes)
        {
            continue;
        }
        best = Some(AcceleratorTopology {
            kind: "dedicated",
            adapter_id: Some(format!(
                "luid_{:08x}_{:08x}",
                desc.AdapterLuid.HighPart as u32, desc.AdapterLuid.LowPart
            )),
            dedicated_bytes: Some(bytes),
            dedicated_used_bytes: None,
            gpu_utilization_percent: None,
        });
    }
    best.unwrap_or_else(AcceleratorTopology::system_only)
}

#[cfg(test)]
mod tests {
    use super::AcceleratorTopology;
    #[test]
    fn system_only_never_invents_vram() {
        let value = AcceleratorTopology::system_only();
        assert_eq!(value.kind, "system-only");
        assert_eq!(value.dedicated_bytes, None);
        assert_eq!(value.dedicated_used_bytes, None);
        assert_eq!(value.gpu_utilization_percent, None);
    }
}
