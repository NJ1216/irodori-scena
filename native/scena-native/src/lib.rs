use pyo3::prelude::*;

mod audio;
mod cue_mix;
mod timeline_mix;
mod timeline_pcm;
mod timeline_peak;

#[pymodule]
fn scena_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(audio::render_overlap_wav, module)?)?;
    module.add_function(wrap_pyfunction!(audio::overlap_following_gain, module)?)?;
    module.add_function(wrap_pyfunction!(cue_mix::mix_pcm_members_wav, module)?)?;
    module.add_function(wrap_pyfunction!(timeline_mix::render_timeline_wav, module)?)?;
    Ok(())
}
