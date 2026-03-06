use adamo_video::config::VideoStreamConfig;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

/// A running video stream handle exposed to Python.
#[pyclass]
struct VideoStream {
    handle: Option<adamo_video::VideoStreamHandle>,
    track_name: String,
}

#[pymethods]
impl VideoStream {
    /// The track name this stream is publishing to.
    #[getter]
    fn track_name(&self) -> &str {
        &self.track_name
    }

    /// Stop the video stream and release all resources.
    fn stop(&mut self) -> PyResult<()> {
        if let Some(handle) = self.handle.take() {
            handle.stop();
        }
        Ok(())
    }

    fn __enter__(slf: Py<Self>) -> Py<Self> {
        slf
    }

    fn __exit__(
        &mut self,
        _exc_type: Option<PyObject>,
        _exc_val: Option<PyObject>,
        _exc_tb: Option<PyObject>,
    ) -> PyResult<bool> {
        self.stop()?;
        Ok(false)
    }
}

impl Drop for VideoStream {
    fn drop(&mut self) {
        if let Some(handle) = self.handle.take() {
            handle.stop();
        }
    }
}

/// Start a video stream.
///
/// Creates a Zenoh session targeting the given QUIC endpoint, opens a GStreamer
/// pipeline for the given source, and publishes encoded video frames.
///
/// Args:
///     quic_endpoint: Zenoh QUIC endpoint (e.g. "quic/zenoh.adamohq.com:443")
///     org: Organization slug
///     robot_name: Robot name for topic namespacing
///     source: Video source — V4L2 device path, GStreamer pipeline, or ROS topic
///     track_name: Optional track name (auto-generated if None)
///     bitrate: Target bitrate in kbps (default 2000)
///     fps: Target framerate (default 30)
///     encoder: Encoder name (auto-detect if None)
///     stereo: Whether this carries stereo frames (default False)
///     fec: Enable Forward Error Correction (default False)
///     nack: Enable NACK retransmission (default False)
///
/// Returns:
///     VideoStream handle
#[pyfunction]
#[pyo3(signature = (quic_endpoint, org, robot_name, source, *, track_name=None, bitrate=2000, fps=30, encoder=None, stereo=false, fec=false, nack=false))]
fn start_video(
    quic_endpoint: &str,
    org: &str,
    robot_name: &str,
    source: &str,
    track_name: Option<String>,
    bitrate: u32,
    fps: u32,
    encoder: Option<String>,
    stereo: bool,
    fec: bool,
    nack: bool,
) -> PyResult<VideoStream> {
    // Initialize logging (harmless if already initialized)
    let _ = env_logger::try_init();

    // Build Zenoh config targeting the QUIC endpoint
    let zenoh_config = {
        let config_json = format!(
            r#"{{
                mode: "client",
                connect: {{ endpoints: ["{quic_endpoint}"] }},
                scouting: {{
                    multicast: {{ enabled: false }},
                    gossip: {{ enabled: false }}
                }}
            }}"#,
        );
        zenoh::Config::from_json5(&config_json)
            .map_err(|e| PyRuntimeError::new_err(format!("Invalid Zenoh config: {e}")))?
    };

    // Open Zenoh session (blocks briefly)
    let rt = tokio::runtime::Runtime::new()
        .map_err(|e| PyRuntimeError::new_err(format!("Failed to create runtime: {e}")))?;
    let session: zenoh::Session = rt
        .block_on(async { zenoh::open(zenoh_config).await })
        .map_err(|e| PyRuntimeError::new_err(format!("Failed to open Zenoh session: {e}")))?;

    let stream_config = VideoStreamConfig {
        track_name,
        bitrate,
        fps,
        encoder,
        stereo,
        fec,
        nack,
    };

    let handle = adamo_video::start_video_stream(session, org, robot_name, source, stream_config)
        .map_err(|e| PyRuntimeError::new_err(format!("Failed to start video stream: {e}")))?;

    let track_name = handle.track_name().to_string();
    Ok(VideoStream {
        handle: Some(handle),
        track_name,
    })
}

/// Detect the best available hardware encoder.
///
/// Probes the GStreamer registry and returns the encoder name
/// (e.g. "vtenc_h264", "nvh264enc", "vah264enc").
#[pyfunction]
fn detect_encoder() -> String {
    adamo_video::detect::detect_encoder().as_str().to_string()
}

/// Native video extension for the Adamo Python SDK.
#[pymodule]
fn _adamo_video(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(start_video, m)?)?;
    m.add_function(wrap_pyfunction!(detect_encoder, m)?)?;
    m.add_class::<VideoStream>()?;
    Ok(())
}
